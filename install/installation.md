# Create an environment with Anaconda

In order to use Coastseg you need to install Python packages in an environment. We recommend you use [Anaconda](https://www.anaconda.com/products/distribution) to install the python packages in an environment for Coastseg.

After you install Anaconda on your PC, open the Anaconda prompt or Terminal in in Mac and Linux and use the `cd` command (change directory) to go the folder where you have downloaded the Coastseg repository.

Create a new environment named `coastseg` with all the required packages by entering these commands:

## Install Coastseg

```
conda create -n coastseg python=3.10
conda activate coastseg
conda install -c conda-forge geopandas earthengine-api scikit-image matplotlib astropy notebook tqdm -y
conda install -c conda-forge leafmap pydensecrf -y
pip install pyqt5 area doodleverse_utils tensorflow
```

### Notes on `pip install tensorflow`

Windows users must use `pip` to install `tensorflow` because the conda version of tensorflow for windows is out of date as of 8/11/2022. The windows version is stuck on v1.14 on [conda-forge](https://anaconda.org/conda-forge/tensorflow).

## Activate Coastseg Environment

All the required packages have now been installed in an environment called coastseg. Always make sure that the environment is activated with:

`conda activate coastseg`
To confirm that you have successfully activated coastseg, your terminal command line prompt should now start with (coastseg).

## ⚠️Installation Errors ⚠️

Use the command `conda clean --all` to clean old packages from your anaconda base environment. Ensure you are not in your coastseg environment or any other environment by running `conda deactivate`, to deactivate any environment you're in before running `conda clean --all`. It is recommended that you have Anaconda prompt (terminal for Mac and Linux) open as an administrator before you attempt to install `coastseg` again.

### Conda Clean Steps

```
conda deactivate
conda clean --all
```