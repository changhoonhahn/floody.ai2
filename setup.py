"""
floody.ai2: zip-code-level flood outcome datasets for studying FEMA's
Community Rating System (CRS).

The code lives in bin/data/ (dataset pipeline) and nb/data/ (check
notebooks); see bin/data/README.md. This setup file installs the
dependencies:

    pip install -e .            # base: FEMA build, downloads, dataset builds, plots
    pip install -e ".[geo]"     # + geospatial steps (prism, wqp, sdwis, blackmarble)
    pip install -e ".[nb]"      # + Jupyter, to run the notebooks in nb/data/
    pip install -e ".[all]"     # everything

The geospatial stack (GDAL-based rasterio/pyogrio, exactextract) installs
most reliably with conda; bin/data/environment.yml defines the "ai2-geo"
environment used to build the data.
"""
from setuptools import setup

BASE = [
    "numpy>=2.4",
    "pandas>=3.0",
    "scipy>=1.17",
    "matplotlib>=3.10",
    "corner>=2.2",
]
GEO = [
    "geopandas>=1.2",
    "shapely>=2.2",
    "pyogrio>=0.13",
    "rasterio>=1.5",
    "exactextract>=0.3",
    "h5py>=3.16",
]
NB = [
    "jupyter",
    "ipykernel>=7.2",
    "nbformat>=5.10",
    "nbconvert>=7.17",
]

setup(
    name="floody_ai2",
    version="0.1.0",
    description="Zip-code-level flood outcome datasets (FEMA NFIP, CRS, water quality, "
                "drinking water, nighttime lights, nursing homes)",
    author="ChangHoon Hahn",
    license="MIT",
    url="https://github.com/changhoonhahn/floody.ai2",
    python_requires=">=3.12",
    py_modules=[],
    install_requires=BASE,
    extras_require={"geo": GEO, "nb": NB, "all": GEO + NB},
)
