# Standard library imports
import os
import logging
import pathlib
from pathlib import Path
from typing import Collection, Dict, Tuple, Union

from coastseg import file_utilities
from coastseg.file_utilities import progress_bar_context

# Third-party imports
import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import pyTMD.constants
import pyTMD.io
import pyTMD.io.model
import pyTMD.predict
import pyTMD.spatial
import pyTMD.time
import pyTMD.utilities
from shapely.geometry import Point

# Logger setup
logger = logging.getLogger(__name__)


def save_csv_per_id(
    df: pd.DataFrame,
    save_location: str,
    filename: str = "timeseries_tidally_corrected",
    id_column_name: str = "transect_id",
):
    new_df = pd.DataFrame()
    unique_ids = df[id_column_name].unique()
    for uid in unique_ids:
        new_filename = f"{uid}_{filename}"
        new_df = df[df[id_column_name] == uid]
        new_df.to_csv(os.path.join(save_location, new_filename))


def correct_all_tides(
    roi_ids: Collection,
    session_name: str,
    reference_elevation: float,
    beach_slope: float,
    use_progress_bar: bool = True,
):
    # validate tide model exists at CoastSeg/tide_model
    model_location = get_tide_model_location()
    # load the regions the tide model was clipped to from geojson file
    tide_regions_file = file_utilities.load_package_resource(
        "tide_model", "tide_regions_map.geojson"
    )
    with progress_bar_context(
        use_progress_bar,
        total=len(roi_ids),
        description=f"Correcting Tides for {len(roi_ids)} ROIs",
    ) as update:
        for roi_id in roi_ids:
            correct_tides(
                roi_id,
                session_name,
                reference_elevation,
                beach_slope,
                model_location,
                tide_regions_file,
                use_progress_bar,
            )
            logger.info(f"{roi_id} was tidally corrected")
            update(f"{roi_id} was tidally corrected")


def save_transect_settings(
    session_path: str,
    reference_elevation: float,
    beach_slope: float,
    filename: str = "transects_settings.json",
) -> None:
    """
    Update and save transect settings with the provided reference elevation and beach slope.

    Parameters:
    -----------
    session_path : str
        Path to the session directory where the transect settings JSON file is located.
    reference_elevation : float
        The reference elevation value to be updated in the transect settings.
    beach_slope : float
        The beach slope value to be updated in the transect settings.
    filename : str, optional
        The name of the JSON file containing the transect settings. Defaults to "transects_settings.json".

    Returns:
    --------
    None

    Notes:
    ------
    The function reads the existing settings file in the session directory (as specified by the
    `filename` parameter), updates the reference elevation and beach slope values, and then
    writes the updated settings back to the same file.

    Raises:
    -------
    FileNotFoundError:
        If the specified settings file does not exist in the given session path.
    """
    transects_settings = file_utilities.read_json_file(
        os.path.join(session_path, filename), raise_error=True
    )
    transects_settings["reference_elevation"] = reference_elevation
    transects_settings["beach_slope"] = beach_slope
    file_utilities.to_file(transects_settings, os.path.join(session_path, filename))


def correct_tides(
    roi_id: str,
    session_name: str,
    reference_elevation: float,
    beach_slope: float,
    model_location: str,
    tide_regions_file: str,
    use_progress_bar: bool = True,
) -> pd.DataFrame:
    """
    Correct the tides for a given Region Of Interest (ROI) using a tide model.

    Parameters:
    -----------
    roi_id : str
        Identifier for the Region Of Interest.
    session_name : str
        Name of the session.
    reference_elevation : float
        Reference elevation value.
    beach_slope : float
        Slope of the beach.
    model_location : str
        Path to the tide model.
    tide_regions_file : str
        Path to the file containing the regions the tide model was clipped to.
    use_progress_bar : bool, optional
        If True, a tqdm progress bar will be displayed. Default is True.

    Returns:
    --------
    pd.DataFrame
        A DataFrame containing tide-corrected time series data for the specified ROI.

    Notes:
    ------
    - This function will set up the tide model, get the time series for the ROI, and predict tides.
    - Tidally corrected time series data will be saved to the session location for the ROI.
    """
    with progress_bar_context(use_progress_bar, total=6) as update:
        # create the settings used to run the tide_model

        update(f"Setting up the tide model : {roi_id}")
        tide_model_config = setup_tide_model_config(model_location)
        update(f"Getting time series for ROI : {roi_id}")
        # load the time series
        raw_timeseries_df = get_timeseries(roi_id, session_name)
        # read the transects from the config_gdf.geojson file
        update(f"Getting transects for ROI : {roi_id}")
        transects_gdf = get_transects(roi_id, session_name)
        # predict the tides for each seaward transect point in the ROI
        update(f"Predicting tides : {roi_id}")
        predicted_tides_df = predict_tides(
            transects_gdf,
            raw_timeseries_df,
            tide_regions_file,
            tide_model_config,
        )
        # Apply tide correction to the time series using the tide predictions
        update(f"Tidally correcting time series for ROI : {roi_id}")

        # optionally save to session location in ROI save the predicted tides to csv
        session_path = file_utilities.get_session_contents_location(
            session_name, roi_id
        )
        # read in transect_settings.json from session_path save the beach slope and reference shoreline
        save_transect_settings(
            session_path, reference_elevation, beach_slope, "transects_settings.json"
        )

        predicted_tides_df.to_csv(os.path.join(session_path, "predicted_tides.csv"))
        tide_corrected_timeseries_df = tidally_correct_timeseries(
            raw_timeseries_df,
            predicted_tides_df,
            reference_elevation,
            beach_slope,
        )
        # optionally save to session location in ROI the tide_corrected_timeseries_df to csv
        tide_corrected_timeseries_df.to_csv(
            os.path.join(session_path, "transect_time_series_tidally_corrected.csv")
        )
        # save a csv for each transect that was tidally corrected
        save_csv_per_id(
            tide_corrected_timeseries_df,
            session_path,
            filename="timeseries_tidally_corrected",
        )
        update(f"{roi_id} was tidally corrected")
    return tide_corrected_timeseries_df


def get_timeseries_location(ROI_ID: str, session_name: str) -> str:
    """
    Retrieves the path to the time series CSV file for a given ROI ID and session name.

    Args:
        ROI_ID (str): The ID of the region of interest.
        session_name (str): The name of the session.

    Returns:
        str: Path to the time series CSV file.

    Raises:
        FileNotFoundError: If the expected file is not found in the specified directory.
    """
    # get the contents of the session directory containing the data for the ROI id
    session_path = file_utilities.get_session_contents_location(session_name, ROI_ID)
    time_series_location = file_utilities.find_file_by_regex(
        session_path, r"^transect_time_series\.csv$"
    )
    return time_series_location


def get_timeseries(ROI_ID: str, session_name: str) -> pd.DataFrame:
    # get the contents of the session directory containing the data for the ROI id
    time_series_location = get_timeseries_location(ROI_ID, session_name)
    raw_timeseries_df = timeseries_read_csv(time_series_location)
    return raw_timeseries_df


def get_transects(roi_id: str, session_name: str):
    # open the sessions directory
    session_path = file_utilities.get_session_location(session_name)
    roi_location = file_utilities.find_matching_directory_by_id(session_path, roi_id)
    if roi_location is not None:
        session_path = roi_location
    # locate the config_gdf.geojson containing the transects
    config_path = file_utilities.find_file_by_regex(
        session_path, r"^config_gdf\.geojson$"
    )
    # Load the GeoJSON file containing transect data
    transects_gdf = read_and_filter_geojson(config_path)
    # get only the transects that intersect with this ROI
    # this may not be necessary because these should have NaN values
    return transects_gdf


def setup_tide_model_config(model_path: str) -> dict:
    return {
        "DIRECTORY": model_path,
        "DELTA_TIME": [0],
        "GZIP": False,
        "MODEL": "FES2014",
        "ATLAS_FORMAT": "netcdf",
        "EXTRAPOLATE": True,
        "METHOD": "spline",
        "TYPE": "drift",
        "TIME": "datetime",
        "EPSG": 4326,
        "FILL_VALUE": np.nan,
        "CUTOFF": 10,
        "METHOD": "bilinear",
        "REGION_DIRECTORY": os.path.join(model_path, "region"),
    }


def get_tide_model_location(location: str = "tide_model"):
    logger.info(f"Checking if tide model exists at {location}")
    if validate_tide_model_exists(location):
        return os.path.abspath(location)
    else:
        raise Exception(
            f"Tide model not found at: '{os.path.abspath(location)}'. Ensure the model is downloaded to this location."
        )


def validate_tide_model_exists(location: str) -> bool:
    """
    Validates if a given directory exists and if it adheres to the tide model structure,
    specifically if it contains sub-directories named "region0" to "region10"
    with the appropriate content.

    Args:
    - location (str): The path to the directory to validate.

    Returns:
    - bool: True if the directory adheres to the expected tide model structure, False otherwise.

    Example:
    >>> validate_tide_model_exists("/path/to/directory")
    True/False
    """

    location = os.path.abspath(location)
    logger.info(f"Tide model absolute path {location}")
    # check if tide directory exists and if the model was clipped to the 10 regions
    if os.path.isdir(location) and contains_sub_directories(location, 10):
        return True
    return False


def sub_directory_contains_files(
    sub_directory_path: str, extension: str, count: int
) -> bool:
    """
    Check if a sub-directory contains a specified number of files with a given extension.

    Args:
    - sub_directory_path (str): The path to the sub-directory.
    - extension (str): The file extension to look for (e.g., '.nc').
    - count (int): The expected number of files with the specified extension.

    Returns:
    - bool: True if the sub-directory contains the exact number of specified files, False otherwise.
    """

    if not os.path.isdir(sub_directory_path):
        raise Exception(
            f" Missing directory {os.path.basename(sub_directory_path)} at {sub_directory_path}"
        )
        return False

    files_with_extension = [
        f for f in os.listdir(sub_directory_path) if f.endswith(extension)
    ]
    # if len(files_with_extension) != count:
    # raise Exception(
    #     f"The tide model was not correctly clipped {os.path.basename(sub_directory_path)} only contained {len(files_with_extension)} when it should have contained {count} files"
    # )
    return len(files_with_extension) == count


def contains_sub_directories(directory_name: str, num_regions: int) -> bool:
    """
    Check if a directory contains sub-directories in the format "regionX/fes2014/load_tide"
    and "regionX/fes2014/ocean_tide", and if each of these sub-directories contains 34 .nc files.

    Args:
    - directory_name (str): The name of the main directory.
    - num_regions (int): The number of regions to check (e.g., for 10 regions, it'll check region0 to region10).

    Returns:
    - bool: True if all conditions are met, False otherwise.
    """

    for i in range(num_regions + 1):
        region_dir = os.path.join(directory_name, f"region{i}")
        load_tide_path = os.path.join(region_dir, "fes2014", "load_tide")
        ocean_tide_path = os.path.join(region_dir, "fes2014", "ocean_tide")

        if not os.path.isdir(region_dir):
            raise Exception(
                f"Tide Model was not clipped correctly. Missing the directory '{os.path.basename(region_dir)}' for region {i} at {region_dir}"
            )

        if not os.path.isdir(load_tide_path):
            raise Exception(
                f"Tide Model was not clipped correctly. Region {i} was missing directory '{os.path.basename(load_tide_path)}' at {load_tide_path}"
            )

        if not os.path.isdir(ocean_tide_path):
            raise Exception(
                f"Tide Model was not clipped correctly. Region {i} was missing directory '{os.path.basename(ocean_tide_path)}' at {ocean_tide_path}"
            )

        if not sub_directory_contains_files(load_tide_path, ".nc", 34):
            raise Exception(
                f"Tide Model was not clipped correctly. Region {i} '{os.path.basename(load_tide_path)}' directory did not contain all 34 .nc files at {load_tide_path}"
            )
        if not sub_directory_contains_files(ocean_tide_path, ".nc", 34):
            raise Exception(
                f"Tide Model was not clipped correctly. Region {i} '{os.path.basename(ocean_tide_path)}' directory did not contain all 34 .nc files at {ocean_tide_path}"
            )

    return True


def get_tide_predictions(
    row: pd.Series, timeseries_df: pd.DataFrame, model_region_directory: str
) -> pd.DataFrame:
    """
    Get tide predictions for a given row.

    Parameters:
    - row: A row from a DataFrame containing transect seaward point to predict tide for.
      Must contain columns "transect_id" and "region_id".
    - timeseries_df: A DataFrame containing time series data for each transect. A DataFrame containing time series data for the transects.
    - model_region_directory: The path to the FES 2014 model region that will be used to compute the tide predictions
    ex."C:/development/doodleverse/CoastSeg/tide_model/region"

    Returns:
    - pd.DataFrame: A DataFrame containing tide predictions for all the dates that the selected transect_id using the
    fes 2014 model region specified in the "region_id".
    """
    transect_id = row["transect_id"]
    region_id = row["region_id"]
    directory = f"{model_region_directory}{region_id}"
    if transect_id not in timeseries_df.columns:
        return None
    dates_for_transect_id_df = timeseries_df[["dates", transect_id]].dropna()
    tide_predictions_df = model_tides(
        row["x"],
        row["y"],
        dates_for_transect_id_df.dates.values,
        transect_id=transect_id,
        directory=directory,
    )
    return tide_predictions_df


def predict_tides_for_df(
    seaward_points_gdf: gpd.GeoDataFrame,
    timeseries_df: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """
    Predict tides for a points in the DataFrame.

    Parameters:
    - seaward_points_gdf: A GeoDataFrame containing seaward points for each transect
    - timeseries_df: A DataFrame containing time series data for each transect. A DataFrame containing time series data for the transects
    - config: Configuration dictionary.
    Must contain key:
    "REGION_DIRECTORY" : contains full path to the fes 2014 model region folder

    Returns:
    - pd.DataFrame: A DataFrame containing predicted tides.
    Contains columns dates,x,y,tide,transect_id
    """
    region_directory = config["REGION_DIRECTORY"]

    # Apply the get_tide_predictions over each row and collect results in a list
    all_tides = seaward_points_gdf.apply(
        lambda row: get_tide_predictions(row, timeseries_df, region_directory), axis=1
    )
    # Filter out None values
    all_tides = all_tides.dropna()

    # Concatenate all the results
    all_tides_df = pd.concat(all_tides.tolist())

    return all_tides_df


def model_tides(
    x,
    y,
    time,
    transect_id: str = "",
    model="FES2014",
    directory=None,
    epsg=4326,
    method="bilinear",
    extrapolate=True,
    cutoff=10.0,
):
    """
    Compute tides at points and times using tidal harmonics.
    If multiple x, y points are provided, tides will be
    computed for all timesteps at each point.

    This function supports any tidal model supported by
    `pyTMD`, including the FES2014 Finite Element Solution
    tide model, and the TPXO8-atlas and TPXO9-atlas-v5
    TOPEX/POSEIDON global tide models.

    This function requires access to tide model data files
    to work. These should be placed in a folder with
    subfolders matching the formats specified by `pyTMD`:
    https://pytmd.readthedocs.io/en/latest/getting_started/Getting-Started.html#directories

    For FES2014 (https://www.aviso.altimetry.fr/es/data/products/auxiliary-products/global-tide-fes/description-fes2014.html):
        - {directory}/fes2014/ocean_tide/
          {directory}/fes2014/load_tide/

    For TPXO8-atlas (https://www.tpxo.net/tpxo-products-and-registration):
        - {directory}/tpxo8_atlas/

    For TPXO9-atlas-v5 (https://www.tpxo.net/tpxo-products-and-registration):
        - {directory}/TPXO9_atlas_v5/

    This function is a minor modification of the `pyTMD`
    package's `compute_tide_corrections` function, adapted
    to process multiple timesteps for multiple input point
    locations. For more info:
    https://pytmd.readthedocs.io/en/stable/user_guide/compute_tide_corrections.html

    Parameters:
    -----------
    x, y : float or list of floats
        One or more x and y coordinates used to define
        the location at which to model tides. By default these
        coordinates should be lat/lon; use `epsg` if they
        are in a custom coordinate reference system.
    time : A datetime array or pandas.DatetimeIndex
        An array containing 'datetime64[ns]' values or a
        'pandas.DatetimeIndex' providing the times at which to
        model tides in UTC time.
    model : string
        The tide model used to model tides. Options include:
        - "FES2014" (only pre-configured option on DEA Sandbox)
        - "TPXO8-atlas"
        - "TPXO9-atlas-v5"
    directory : string
        The directory containing tide model data files. These
        data files should be stored in sub-folders for each
        model that match the structure provided by `pyTMD`:
        https://pytmd.readthedocs.io/en/latest/getting_started/Getting-Started.html#directories
        For example:
        - {directory}/fes2014/ocean_tide/
          {directory}/fes2014/load_tide/
        - {directory}/tpxo8_atlas/
        - {directory}/TPXO9_atlas_v5/
    epsg : int
        Input coordinate system for 'x' and 'y' coordinates.
        Defaults to 4326 (WGS84).
    method : string
        Method used to interpolate tidal contsituents
        from model files. Options include:
        - bilinear: quick bilinear interpolation
        - spline: scipy bivariate spline interpolation
        - linear, nearest: scipy regular grid interpolations
    extrapolate : bool
        Whether to extrapolate tides for locations outside of
        the tide modelling domain using nearest-neighbor
    cutoff : int or float
        Extrapolation cutoff in kilometers. Set to `np.inf`
        to extrapolate for all points.

    Returns
    -------
    A pandas.DataFrame containing tide heights for all the xy points and their corresponding time
    """
    # Check tide directory is accessible
    if directory is not None:
        directory = pathlib.Path(directory).expanduser()
        if not directory.exists():
            raise FileNotFoundError("Invalid tide directory")

    # Validate input arguments
    assert method in ("bilinear", "spline", "linear", "nearest")

    # Get parameters for tide model; use custom definition file for
    model = pyTMD.io.model(directory, format="netcdf", compressed=False).elevation(
        model
    )

    # If time passed as a single Timestamp, convert to datetime64
    if isinstance(time, pd.Timestamp):
        time = time.to_datetime64()

    # Handle numeric or array inputs
    x = np.atleast_1d(x)
    y = np.atleast_1d(y)
    time = np.atleast_1d(time)

    # Determine point and time counts
    assert len(x) == len(y), "x and y must be the same length"
    n_points = len(x)
    n_times = len(time)

    # Converting x,y from EPSG to latitude/longitude
    try:
        # EPSG projection code string or int
        crs1 = pyproj.CRS.from_epsg(int(epsg))
    except (ValueError, pyproj.exceptions.CRSError):
        # Projection SRS string
        crs1 = pyproj.CRS.from_string(epsg)

    # Output coordinate reference system
    crs2 = pyproj.CRS.from_epsg(4326)
    transformer = pyproj.Transformer.from_crs(crs1, crs2, always_xy=True)
    lon, lat = transformer.transform(x.flatten(), y.flatten())

    # Convert datetime
    timescale = pyTMD.time.timescale().from_datetime(time.flatten())
    n_points = len(x)
    # number of time points
    n_times = len(time)

    if model.format == "FES":
        amp, ph = pyTMD.io.FES.extract_constants(
            lon,
            lat,
            model.model_file,
            type=model.type,
            version=model.version,
            method=method,
            extrapolate=extrapolate,
            cutoff=cutoff,
            scale=model.scale,
            compressed=model.compressed,
        )

        # Available model constituents
        c = model.constituents

        # Delta time (TT - UT1)
        # calculating the difference between Terrestrial Time (TT) and UT1 (Universal Time 1),
        deltat = timescale.tt_ut1

    # Calculate complex phase in radians for Euler's
    cph = -1j * ph * np.pi / 180.0

    # Calculate constituent oscillation
    hc = amp * np.exp(cph)

    # Repeat constituents to length of time and number of input
    # coords before passing to `predict_tide_drift`

    # deltat likely represents the time interval between successive data points or time instances.
    # t =  replicating the timescale.tide array n_points times
    # hc = creates an array with the tidal constituents repeated for each time instance
    # Repeat constituents to length of time and number of input
    # coords before passing to `predict_tide_drift`
    t, hc, deltat = (
        np.tile(timescale.tide, n_points),
        hc.repeat(n_times, axis=0),
        np.tile(deltat, n_points),
    )

    # Predict tidal elevations at time and infer minor corrections
    npts = len(t)
    tide = np.ma.zeros((npts), fill_value=np.nan)
    tide.mask = np.any(hc.mask, axis=1)

    # Predict tides
    tide.data[:] = pyTMD.predict.drift(
        t, hc, c, deltat=deltat, corrections=model.format
    )
    minor = pyTMD.predict.infer_minor(t, hc, c, deltat=deltat, corrections=model.format)
    tide.data[:] += minor.data[:]

    # Replace invalid values with fill value
    tide.data[tide.mask] = tide.fill_value
    if transect_id:
        df = pd.DataFrame(
            {
                "dates": np.tile(time, n_points),
                "x": np.repeat(x, n_times),
                "y": np.repeat(y, n_times),
                "tide": tide,
                "transect_id": transect_id,
            }
        )
        df["dates"] = pd.to_datetime(df["dates"], utc=True)
        df.set_index("dates")
        return df
    else:
        df = pd.DataFrame(
            {
                "dates": np.tile(time, n_points),
                "x": np.repeat(x, n_times),
                "y": np.repeat(y, n_times),
                "tide": tide,
            }
        )
        df["dates"] = pd.to_datetime(df["dates"], utc=True)
        df.set_index("dates")
        return df


def get_seaward_points(
    transects_gdf: gpd.GeoDataFrame,
) -> Dict[str, Union[Point, None]]:
    """
    Extracts the seaward points from a given GeoDataFrame containing transects.

    Parameters:
    - transects_gdf: A GeoDataFrame containing transect data.

    Returns:
    - dict: A dictionary where keys are transect IDs and values are the seaward points (or None if not available).
    """
    transect_seaward_points = {}
    for index, row in transects_gdf.iterrows():
        points = list(row["geometry"].coords)
        seaward_point = points[1] if len(points) > 1 else None
        transect_seaward_points[row["id"]] = seaward_point
    return transect_seaward_points


def get_seaward_points_gdf(transects_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Creates a GeoDataFrame containing the seaward points from a given GeoDataFrame containing transects.

    Parameters:
    - transects_gdf: A GeoDataFrame containing transect data.

    Returns:
    - gpd.GeoDataFrame: A GeoDataFrame containing the seaward points for all of the transects
    Contains columns transect_id,x,y
    """
    data = []

    for index, row in transects_gdf.iterrows():
        points = list(row["geometry"].coords)
        seaward_point = points[1] if len(points) > 1 else (None, None)

        # Append data for each transect to the data list
        data.append(
            {"transect_id": row["id"], "x": seaward_point[0], "y": seaward_point[1]}
        )

    # Convert the data list to a pandas DataFrame
    df = pd.DataFrame(data)

    # Create a GeoDataFrame with geometry as Point objects from x and y columns
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.x, df.y))
    gdf = gdf.set_crs("epsg:4326")

    return gdf


def read_and_filter_geojson(
    file_path: str,
    columns_to_keep: Tuple[str, ...] = ("id", "type", "geometry"),
    feature_type: str = "transect",
) -> gpd.GeoDataFrame:
    """
    Read and filter a GeoJSON file based on specified columns and feature type.

    Parameters:
    - file_path: Path to the GeoJSON file.
    - columns_to_keep: A tuple containing column names to be retained in the resulting GeoDataFrame. Default is ("id", "type", "geometry").
    - feature_type: Type of feature to be retained in the resulting GeoDataFrame. Default is "transect".

    Returns:
    - gpd.GeoDataFrame: A filtered GeoDataFrame.
    """
    # Read the GeoJSON file into a GeoDataFrame
    gdf = gpd.read_file(file_path)
    # Drop all other columns in place
    gdf.drop(
        columns=[col for col in gdf.columns if col not in columns_to_keep], inplace=True
    )
    # Filter the features with "type" equal to the specified feature_type
    filtered_gdf = gdf[gdf["type"] == feature_type]

    return filtered_gdf


def load_regions_from_geojson(geojson_path: str) -> gpd.GeoDataFrame:
    """
    Load regions from a GeoJSON file and assign a region_id based on index.

    Parameters:
    - geojson_path: Path to the GeoJSON file containing regions.

    Returns:
    - gpd.GeoDataFrame: A GeoDataFrame containing the loaded regions with an added 'region_id' column.
    """
    gdf = gpd.read_file(geojson_path)
    gdf["region_id"] = gdf.index
    return gdf


def perform_spatial_join(
    seaward_points_gdf: gpd.GeoDataFrame, regions_gdf: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """
    Perform a spatial join between seaward points and regions based on intersection.

    Parameters:
    - seaward_points_gdf: A GeoDataFrame containing seaward points.
    - regions_gdf: A GeoDataFrame containing regions.

    Returns:
    - gpd.GeoDataFrame: A GeoDataFrame resulting from the spatial join.
    """
    joined_gdf = gpd.sjoin(
        seaward_points_gdf, regions_gdf, how="left", predicate="intersects"
    )
    joined_gdf.drop(columns="index_right", inplace=True)
    return joined_gdf


def model_tides_for_all(
    seaward_points_gdf: gpd.GeoDataFrame,
    timeseries_df: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """
    Model tides for all points in the provided GeoDataFrame.

    Parameters:
    - seaward_points_gdf: A GeoDataFrame containing seaward point for each transect.
    - timeseries_df: A DataFrame containing time series data for each transect. A DataFrame containing time series data for tides.
    - config: Configuration dictionary.

    Returns:
    - pd.DataFrame: A DataFrame containing predicted tides for all points.
    """
    return predict_tides_for_df(seaward_points_gdf, timeseries_df, config)


def model_tides_by_region_id(
    seaward_points_gdf: gpd.GeoDataFrame,
    timeseries_df: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """
    Model tides for each unique region ID in the provided GeoDataFrame.

    Parameters:
    - seaward_points_gdf: A GeoDataFrame containing seaward point for each transect.
    - timeseries_df: A DataFrame containing time series data for each transect. A DataFrame containing time series data for tides.
    - config: Configuration dictionary.

    Returns:
    - pd.DataFrame: A DataFrame containing predicted tides segmented by region ID.
    """
    unique_ids = seaward_points_gdf["region_id"].unique()
    all_tides_dfs = []

    for uid in unique_ids:
        subset_gdf = seaward_points_gdf[seaward_points_gdf["region_id"] == uid]
        tides_for_region_df = predict_tides_for_df(subset_gdf, timeseries_df, config)
        all_tides_dfs.append(tides_for_region_df)

    return pd.concat(all_tides_dfs)


def handle_tide_predictions(
    seaward_points_gdf: gpd.GeoDataFrame,
    timeseries_df: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """
    Handle tide predictions based on the number of unique region IDs in the provided GeoDataFrame.

    Parameters:
    - seaward_points_gdf: A GeoDataFrame containing seaward point for each transect.
    - timeseries_df: A DataFrame containing time series data for each transect. A DataFrame containing time series data for each transect.
    - config: Configuration dictionary.

    Returns:
    - pd.DataFrame: A DataFrame containing predicted tides.
    """
    if seaward_points_gdf["region_id"].nunique() == 1:
        all_tides_df = model_tides_for_all(seaward_points_gdf, timeseries_df, config)
    else:
        all_tides_df = model_tides_by_region_id(
            seaward_points_gdf, timeseries_df, config
        )
    return all_tides_df


def predict_tides(
    transects_gdf: gpd.GeoDataFrame,
    timeseries_df: pd.DataFrame,
    model_regions_geojson_path: str,
    config: dict,
) -> pd.DataFrame:
    """
    Predict tides based on input data and configurations.

    Parameters:
    - geojson_file_path: Path to the GeoJSON file containing transect data.
    - timeseries_df: A DataFrame containing time series data for each transect. A DataFrame containing raw time series data.
    - model_regions_geojson_path: Path to the GeoJSON file containing model regions.
    - config: Configuration dictionary.

    Returns:
    - pd.DataFrame: A DataFrame containing predicted tides.
    """
    # Read in the model regions from a GeoJSON file
    regions_gdf = load_regions_from_geojson(model_regions_geojson_path)
    # Get the seaward points
    seaward_points_gdf = get_seaward_points_gdf(transects_gdf)
    # Perform a spatial join to get the region_id for each point in seaward_points_gdf
    regional_seaward_points_gdf = perform_spatial_join(seaward_points_gdf, regions_gdf)
    # predict the tides
    all_tides_df = handle_tide_predictions(
        regional_seaward_points_gdf, timeseries_df, config
    )
    return all_tides_df


def convert_transect_ids_to_rows(df):
    """
    Reshapes the timeseries data so that transect IDs become rows.

    Args:
    - df (DataFrame): Input data with transect IDs as columns.

    Returns:
    - DataFrame: Reshaped data with transect IDs as rows.
    """
    reshaped_df = df.melt(
        id_vars="dates", var_name="transect_id", value_name="cross_distance"
    )
    return reshaped_df.dropna()


def apply_tide_correction(
    df: pd.DataFrame, reference_elevation: float, beach_slope: float
):
    """
    Applies tidal correction to the timeseries data.

    Args:
    - df (DataFrame): Input data with tide predictions and timeseries data.
    - reference_elevation (float): Reference elevation value.
    - beach_slope (float): Beach slope value.

    Returns:
    - DataFrame: Tidally corrected data.
    """
    correction = (df["tide"] - reference_elevation) / beach_slope
    df["cross_distance"] = df["cross_distance"] + correction
    return df.drop(columns=["correction"], errors="ignore")


def merge_dataframes(df1, df2, columns_to_merge_on=set(["transect_id", "dates"])):
    """
    Merges two DataFrames based on column names provided in columns_to_merge_on by default
    merges on "transect_id", "dates".

    Args:
    - df1 (DataFrame): First DataFrame.
    - df2 (DataFrame): Second DataFrame.
    - columns_to_merge_on(collection): column names to merge on
    Returns:
    - DataFrame: Merged data.
    """
    merged_df = pd.merge(df1, df2, on=list(columns_to_merge_on), how="inner")
    return merged_df.drop_duplicates(ignore_index=True)


def timeseries_read_csv(file_path):
    """
    Reads a CSV file into a DataFrame and performs necessary preprocessing.

    Args:
    - file_path (str): Path to the CSV file.

    Returns:
    - DataFrame: Processed data.
    """
    df = pd.read_csv(file_path, parse_dates=["dates"])
    df["dates"] = pd.to_datetime(df["dates"], utc=True)
    for column in ["x", "y", "Unnamed: 0"]:
        if column in df.columns:
            df.drop(columns=column, inplace=True)
    return df


def tidally_correct_timeseries(
    timeseries_df: pd.DataFrame,
    tide_predictions_df: pd.DataFrame,
    reference_elevation: float,
    beach_slope: float,
) -> pd.DataFrame:
    """
    Applies tidal correction to the timeseries data and saves the tidally corrected data to a csv file

    Args:
    - timeseries_df (pd.DataFrame): A DataFrame containing time series data for each transect. A DataFrame containing raw time series data.
    - tide_predictions_df (pd.DataFrame):A DataFrame containing predicted tides each transect's seaward point in the timeseries
    - reference_elevation (float): Reference elevation value.
    - beach_slope (float): Beach slope value.

    Returns:
        - pd.DataFrame: A DataFrame containing the timeseries_df that's been tidally corrected with the predicted tides
    """
    timeseries_df = convert_transect_ids_to_rows(timeseries_df)
    merged_df = merge_dataframes(tide_predictions_df, timeseries_df)
    corrected_df = apply_tide_correction(merged_df, reference_elevation, beach_slope)
    return corrected_df


def get_location(filename: str, check_parent_directory: bool = False) -> Path:
    """
    Get the absolute path to a specified file.

    The function searches for the file in the directory where the script is located.
    Optionally, it can also check the parent directory.

    Parameters:
    - filename (str): The name of the file for which the path is sought.
    - check_parent_directory (bool): If True, checks the parent directory for the file.
      Default is False.

    Returns:
    - Path: The absolute path to the file.

    Raises:
    - FileNotFoundError: If the file is not found in the specified location(s).
    """
    search_dir = Path(__file__).parent
    if check_parent_directory:
        # Move up to the parent directory and then to 'tide_model'
        file_path = search_dir.parent / filename
    else:
        file_path = search_dir / filename
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)
    return file_path


def setup_tide_model_config(model_path: str) -> dict:
    return {
        "DIRECTORY": model_path,
        "DELTA_TIME": [0],
        "GZIP": False,
        "MODEL": "FES2014",
        "ATLAS_FORMAT": "netcdf",
        "EXTRAPOLATE": True,
        "METHOD": "spline",
        "TYPE": "drift",
        "TIME": "datetime",
        "EPSG": 4326,
        "FILL_VALUE": np.nan,
        "CUTOFF": 10,
        "METHOD": "bilinear",
        "REGION_DIRECTORY": os.path.join(model_path, "region"),
    }