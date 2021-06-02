from abc import abstractmethod
import os
import time
import functools
import logging
import hcipy
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from pastis.config import CONFIG_PASTIS
from pastis.e2e_simulators.luvoir_imaging import LuvoirA_APLC
from pastis.matrix_generation.matrix_building_numerical import PastisMatrix
import pastis.plotting as ppl
import pastis.util as util

log = logging.getLogger()
matplotlib.rc('image', origin='lower')
matplotlib.rc('pdf', fonttype=42)


class PastisMatrixEfields(PastisMatrix):
    instrument = None

    def __init__(self, design=None, initial_path='', saveefields=True, saveopds=True):
        super().__init__(design=design, initial_path=initial_path)

        self.save_efields = saveefields
        self.saveopds = saveopds
        self.calculate_one_mode = None
        self.efields_per_mode = []

        os.makedirs(os.path.join(self.resDir, 'efields'), exist_ok=True)

    def calc(self):
        start_time = time.time()

        self.calculate_ref_efield()
        self.setup_deformable_mirror()
        self.setup_single_mode_function()
        self.calculate_efields()
        self.calculate_pastis_matrix_from_efields()

        end_time = time.time()
        log.info(
            f'Runtime for PastisMatrixEfields().calc(): {end_time - start_time}sec = {(end_time - start_time) / 60}min')
        log.info(f'Data saved to {self.resDir}')

    def calculate_efields(self):
        for i in range(self.number_all_modes):
            self.efields_per_mode.append(self.calculate_one_mode(i))
        self.efields_per_mode = np.array(self.efields_per_mode)

    def calculate_pastis_matrix_from_efields(self):
        self.matrix_pastis = pastis_matrix_from_efields(self.efields_per_mode, self.efield_ref, self.norm, self.dh_mask, self.wfe_aber)

        # Save matrix to file
        filename_matrix = f'pastis_matrix'
        hcipy.write_fits(self.matrix_pastis, os.path.join(self.resDir, filename_matrix + '.fits'))
        ppl.plot_pastis_matrix(self.matrix_pastis, self.wvln * 1e9, out_dir=self.resDir, save=True)  # convert wavelength to nm
        log.info(f'PASTIS matrix saved to: {os.path.join(self.resDir, filename_matrix + ".fits")}')

    @abstractmethod
    def calculate_ref_efield(self):
        pass

    @abstractmethod
    def setup_deformable_mirror(self):
        pass

    @abstractmethod
    def setup_single_mode_function(self):
        pass


def pastis_matrix_from_efields(electric_fields, efield_ref, direct_norm, dh_mask, wfe_aber):

    # Calculate the semi-analytical PASTIS matrix from the individual E-fields
    matrix_pastis_half = calculate_semi_analytic_pastis_from_efields(electric_fields, efield_ref, direct_norm, dh_mask)

    # Symmetrize the half-PASTIS matrix
    log.info('Symmetrizing PASTIS matrix')
    matrix_pastis = util.symmetrize(matrix_pastis_half)

    # Normalize PASTIS matrix by input aberration
    matrix_pastis /= np.square(wfe_aber * 1e9)

    return matrix_pastis


def calculate_semi_analytic_pastis_from_efields(efields, efield_ref, direct_norm, dh_mask):

    # Create empty matrix
    nb_modes = efields.shape[0]
    matrix_pastis_half = np.zeros([nb_modes, nb_modes])

    for pair in util.segment_pairs_non_repeating(nb_modes):
        intensity_im = np.real((efields[pair[0]].electric_field - efield_ref) * np.conj(efields[pair[1]].electric_field - efield_ref))
        contrast = util.dh_mean(intensity_im / direct_norm, dh_mask)
        matrix_pastis_half[pair[0], pair[1]] = contrast
        log.info(f'Calculated contrast for pair {pair[0]}-{pair[1]}: {contrast}')

    return matrix_pastis_half


class MatrixEfieldLuvoirA(PastisMatrixEfields):
    instrument = 'LUVOIR'

    def __init__(self, design='small', max_local_zernike=3, initial_path='', saveefields=True, saveopds=True):
        super().__init__(design=design, initial_path=initial_path, saveefields=saveefields, saveopds=saveopds)
        self.max_local_zernike = max_local_zernike

    def calculate_ref_efield(self):
        optics_input = os.path.join(util.find_repo_location(), CONFIG_PASTIS.get('LUVOIR', 'optics_path_in_repo'))
        sampling = CONFIG_PASTIS.getfloat('LUVOIR', 'sampling')
        self.luvoir = LuvoirA_APLC(optics_input, self.design, sampling)
        self.dh_mask = self.luvoir.dh_mask

        # Calculate contrast normalization factor from direct PSF (intensity)
        _unaberrated_coro_psf, direct = self.luvoir.calc_psf(ref=True)
        self.norm = np.max(direct)

        # Calculate reference E-field in focal plane, without any aberrations applied
        unaberrated_ref_efield, _inter = self.luvoir.calc_psf(return_intermediate='efield')
        self.efield_ref = unaberrated_ref_efield.electric_field

    def setup_deformable_mirror(self):
        log.info(f'Creating segmented mirror with {self.max_local_zernike} local modes each...')
        self.luvoir.create_segmented_mirror(self.max_local_zernike)
        self.number_all_modes = self.luvoir.sm.num_actuators
        log.info(f'Total number of modes: {self.number_all_modes}')

    def setup_single_mode_function(self):
        self.calculate_one_mode = functools.partial(_luvoir_matrix_single_mode, self.number_all_modes, self.wfe_aber,
                                                    self.luvoir, self.resDir, self.save_efields, self.saveopds)


def _luvoir_matrix_single_mode(number_all_modes, wfe_aber, luvoir_sim, resDir, saveefields, saveopds, mode_no):

    log.info(f'MODE NUMBER: {mode_no}')

    # Apply calibration aberration to used mode
    all_modes = np.zeros(number_all_modes)
    all_modes[mode_no] = wfe_aber / 2
    luvoir_sim.sm.actuators = all_modes

    # Calculate coronagraphic E-field
    efield_focal_plane, inter = luvoir_sim.calc_psf(return_intermediate='efield')

    if saveefields:
        fname_real = f'efield_real_mode{mode_no}'
        hcipy.write_fits(efield_focal_plane.real, os.path.join(resDir, 'efields', fname_real + '.fits'))
        fname_imag = f'efield_imag_mode{mode_no}'
        hcipy.write_fits(efield_focal_plane.imag, os.path.join(resDir, 'efields', fname_imag + '.fits'))

    if saveopds:
        opd_name = f'opd_mode_{mode_no}'
        plt.clf()
        hcipy.imshow_field(inter['seg_mirror'].phase, grid=luvoir_sim.aperture.grid, mask=luvoir_sim.aperture, cmap='RdBu')
        plt.savefig(os.path.join(resDir, 'OTE_images', opd_name + '.pdf'))

    return efield_focal_plane