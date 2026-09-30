"""Make small, public test data for the Linux CI tests.

Downloads PDB entry 1CBS and calculates map coefficients from its model with
gemmi, written as the two kinds of MTZ Harry Spotter reads:
  - phenix/final.mtz : FoFo / PHFc                       (time-resolved Fo-Fo)
  - dimple/final.mtz : FWT / PHWT + DELFWT / PHDELWT      (apo screening)
No real experimental data is involved.
"""
import os
import sys
import urllib.request

import gemmi
import numpy as np

out = sys.argv[1] if len(sys.argv) > 1 else "testdata"
os.makedirs(out, exist_ok=True)
pdb = os.path.join(out, "1cbs.pdb")
if not os.path.exists(pdb):
    urllib.request.urlretrieve("https://files.rcsb.org/download/1CBS.pdb", pdb)

st = gemmi.read_structure(pdb)
st.remove_hydrogens()
st.setup_entities()
dc = gemmi.DensityCalculatorX()
dc.d_min = 2.0
dc.set_grid_cell_and_spacegroup(st)
dc.put_model_density_on_grid(st[0])
asu = gemmi.transform_map_to_f_phi(dc.grid).prepare_asu_data(dmin=dc.d_min)
amp = np.abs(asu.value_array)
phase = np.angle(asu.value_array, deg=True)


def write_mtz(path, column_pairs):
    mtz = gemmi.Mtz(with_base=True)
    mtz.spacegroup = st.find_spacegroup()
    mtz.set_cell_for_all(st.cell)
    mtz.add_dataset("synthetic")
    columns = [asu.miller_array.astype(np.float32)]
    for f_col, phi_col in column_pairs:
        mtz.add_column(f_col, "F")
        mtz.add_column(phi_col, "P")
        columns += [amp[:, None], phase[:, None]]
    mtz.set_data(np.hstack(columns).astype(np.float32))
    mtz.write_to_file(path)


for kind, pairs in (("phenix", [("FoFo", "PHFc")]),
                    ("dimple", [("FWT", "PHWT"), ("DELFWT", "PHDELWT")])):
    d = os.path.join(out, kind)
    os.makedirs(d, exist_ok=True)
    write_mtz(os.path.join(d, "final.mtz"), pairs)
    st.write_pdb(os.path.join(d, "final.pdb"))
print(f"test data in {out}: {len(asu.miller_array)} reflections, cell {st.cell}, {st.spacegroup_hm}")
