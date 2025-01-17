import numpy as np
from pastis.config import CONFIG_PASTIS
from pastis.matrix_generation.matrix_from_efields import MatrixEfieldLuvoirA


if __name__ == '__main__':

    APLC_DESIGN = 'small'
    DM = 'harris_seg_mirror'   # Possible: "seg_mirror", "harris_seg_mirror", "zernike_mirror"

    # Needed for Harris mirror
    fpath = CONFIG_PASTIS.get('LUVOIR', 'harris_data_path')  # path to Harris spreadsheet
    pad_orientations = np.pi / 2 * np.ones(120)

    DM_SPEC = (fpath, pad_orientations, False, True, False)
    # DM_SPEC = tuple or int, specification for the used DM -
    #    for seg_mirror: int, number of local Zernike modes on each segment
    #    for harris_seg_mirror: tuple (string, array, bool, bool, bool), absolute path to Harris spreadsheet, pad orientations, choice of Harris mode sets (thermal, mechanical, other)
    #    for zernike_mirror: int, number of global Zernikes

    # First generate a couple of matrices
    run_matrix = MatrixEfieldLuvoirA(which_dm=DM, dm_spec=DM_SPEC, design=APLC_DESIGN,
                                     initial_path=CONFIG_PASTIS.get('local', 'local_data_path'))
    run_matrix.calc()
    dir_run = run_matrix.overall_dir
    print(f'All saved to {dir_run}.')
