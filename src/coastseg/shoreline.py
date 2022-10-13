# Standard library imports
import logging
import os
# Internal dependencies imports
from src.coastseg.exceptions import DownloadError
from src.coastseg import common
# External dependencies imports
import geopandas as gpd
import pandas as pd
import numpy as np
from fiona.errors import DriverError
from ipyleaflet import GeoJSON

logger = logging.getLogger(__name__)
logger.info("I am a log from %s",__name__)

class Shoreline():
    """ Shoreline: contains the shorelines within a region specified by bbox (bounding box)
    """
    LAYER_NAME = 'shoreline'
    def __init__(self,bbox:gpd.GeoDataFrame=None,
                 shoreline: gpd.GeoDataFrame=None,
                 filename:str=None):
        self.gdf = gpd.GeoDataFrame()
        self.filename="shoreline.geojson"
        if shoreline is not None:
            if not shoreline.empty:
                self.gdf = shoreline
        if bbox is not None:
            if not bbox.empty:
                logger.info("Creating shoreline geodataframe")
                self.gdf = self.create_geodataframe(bbox)
        
        if filename:
            self.filename=filename
            
    def create_geodataframe(self, bbox:gpd.GeoDataFrame, crs:str='EPSG:4326') -> gpd.GeoDataFrame:
        """Creates a geodataframe with the crs specified by crs
        Args:
            rectangle (dict): geojson dictionary
            crs (str, optional): coordinate reference system string. Defaults to 'EPSG:4326'.

        Returns:
            gpd.GeoDataFrame: geodataframe with geometry column = rectangle and given crs
        """
        shoreline = None
        # geodataframe to hold all shorelines in bbox
        shorelines_in_bbox_gdf = gpd.GeoDataFrame()
        # shoreline files that intersect with bbox
        intersecting_shoreline_files = self.get_intersecting_files(bbox)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # for each shoreline file clip it to bbox
        for file in list(intersecting_shoreline_files.keys()):
            shoreline_path=os.path.abspath(os.path.join(script_dir,"shorelines",file))
            # Check if the shoreline exists if it doesn't download it
            if  os.path.exists(shoreline_path):
                print(f"\n Loading the file {os.path.basename(shoreline_path)} now.")
                try:
                    shoreline=common.read_gpd_file(shoreline_path)
                except DriverError as driver_error:
                    print(driver_error)
                    print(f"\n ERROR!!\n The geojson shoreline file was corrupted\n{shoreline_path}")
                    print("Please raise an issue on GitHub with the shoreline name.\n https://github.com/SatelliteShorelines/CoastSeg/issues \n")
                    continue #if the geojson file cannot be read then skip this file
            else:
                print("\n The geojson shoreline file does not exist. Downloading it now.")
                logger.info(f"{file} did not exist. Downloading it.")
                # Download shoreline geojson from Zenodo
                dataset_id=intersecting_shoreline_files[file]
                try:
                    self.download_shoreline(file, dataset_id)
                # If a file is not online skip it and print error message
                # error message tells user to submit an issue
                except DownloadError as download_exception:
                    print(download_exception)
                    logger.error(f"{file} was not online.")
                    continue
                shoreline_path=os.path.abspath(os.path.join(script_dir,"shorelines",file))
                shoreline=common.read_gpd_file(shoreline_path)

            shoreline.drop(shoreline.columns.difference(['geometry',
                                                         'river_label',
                                                         'ERODIBILITY',
                                                         'CSU_ID',
                                                         'turbid_label',
                                                         'slope_label',
                                                         'sinuosity_label',
                                                         'TIDAL_RANGE',
                                                         'MEAN_SIG_WAVEHEIGHT']), 'columns',inplace=True)
            # Create a single dataframe to hold all shorelines from all files
            shoreline_in_bbox=common.clip_to_bbox(shoreline, bbox)
            if shorelines_in_bbox_gdf.empty:
                    shorelines_in_bbox_gdf = shoreline_in_bbox
            elif not shorelines_in_bbox_gdf.empty:
                    # Combine shorelines from different files into single geodataframe 
                    shorelines_in_bbox_gdf = gpd.GeoDataFrame(pd.concat([shorelines_in_bbox_gdf, shoreline_in_bbox], ignore_index=True))
            
        if shorelines_in_bbox_gdf.empty:
            print("No shoreline found here.")
            logger.warning("No shoreline found here.")
        
        return shorelines_in_bbox_gdf
    
    def style_layer(self, geojson: dict, layer_name :str) -> "ipyleaflet.GeoJSON":
        """Return styled GeoJson object with layer name

        Args:
            geojson (dict): geojson dictionary to be styled
            layer_name(str): name of the GeoJSON layer

        Returns:
            "ipyleaflet.GeoJSON": shoreline as GeoJSON layer styled with yellow dashes
        """
        assert geojson != {}, "ERROR.\n Empty geojson cannot be drawn onto  map"
        return GeoJSON(
            data=geojson,
            name=layer_name,
            style={
                'color': 'yellow',
                'fill_color': 'yellow',
                'opacity': 1,
                'dashArray': '5',
                'fillOpacity': 0.5,
                'weight': 4},
            hover_style={
                'color': 'white',
                'dashArray': '4',
                'fillOpacity': 0.7},
        )
            
    def download_shoreline(self, filename : str ,dataset_id : str = '6917358'):
        """Downloads the shoreline file from zenodo

        Args:
            filename (str): name of file to download
            dataset_id (str, optional): zenodo id of file. Defaults to '6917358'.
        """        
        root_url = 'https://zenodo.org/record/' + dataset_id + '/files/'
        # Create the directory to hold the downloaded shorelines from Zenodo
        script_dir = os.path.dirname(os.path.abspath(__file__))
        shoreline_dir = os.path.abspath(os.path.join(script_dir,"shorelines"))
        if not os.path.exists(shoreline_dir):
            os.mkdir(shoreline_dir)
            logger.info(f"Created shoreline directory: {shoreline_dir}")
        # outfile : location where  model id saved
        outfile = os.path.abspath(os.path.join(shoreline_dir, filename))
        # Download the model from Zenodo
        if not os.path.exists(outfile):
            url = (root_url + filename+"?download=1")
            logger.info(f'Retrieving: {url}')
            logger.info(f'Retrieving file: {outfile}')
            print(f'Retrieving: {url}')
            print(f"Retrieving file: {outfile}")
            common.download_url(url, outfile,filename=filename)

    def get_intersecting_files(self, bbox : gpd.geodataframe)-> dict:
        """Given bounding box (bbox) returns a list of shoreline filenames whose
        contents intersect with bbox

        Args:
            gpd_bbox (geopandas.geodataframe.GeoDataFrame): bounding box being searched for shorelines

        Returns:
            dict: intersecting_files containing filenames whose contents intersect with bbox
        """      
        WORLD_DATASET_ID = '6917963'
        USA_DATASET_ID = '7033367'
        # filenames where transects/shoreline's bbox intersect bounding box drawn by user
        intersecting_files={}
        # dataframe containing total bounding box for each shoreline file
        usa_total_bounds_df=self.load_total_bounds_df('usa')
        world_total_bounds_df=self.load_total_bounds_df('world')
        # intersecting_files filenames where transects/shoreline's bbox intersect bounding box drawn by user
        intersecting_files={}
        total_bounds=[usa_total_bounds_df,world_total_bounds_df]
        # Add filenames of interesting shoreline in both the usa and world shorelines to intersecting_files
        for count,bounds_df in enumerate(total_bounds):
            for filename in bounds_df.index:
                minx, miny, maxx, maxy=bounds_df.loc[filename]
                intersection_df = bbox.cx[minx:maxx, miny:maxy]
                # save filenames where gpd_bbox & bounding box for set of transects or shorelines intersect
                if intersection_df.empty == False and count == 0:
                    intersecting_files[filename]=USA_DATASET_ID     
                if intersection_df.empty == False and count == 1:
                    intersecting_files[filename] = WORLD_DATASET_ID           
        return intersecting_files
 
    def load_total_bounds_df(self,location : str ='usa') -> pd.DataFrame:
        """Returns dataframe containing total bounds for each set of shorelines in the csv file specified by location

        Args:
            location (str, optional): determines whether usa or world shoreline bounding boxes are loaded. Defaults to 'usa'.
            can be either 'world' or 'usa'
            
        Returns:
            pd.DataFrame:  Returns dataframe containing total bounds for each set of shorelines
        """        
        # Load in the total bounding box from csv
        # Create the directory to hold the downloaded shorelines from Zenodo
        script_dir = os.path.dirname(os.path.abspath(__file__))
        bounding_box_dir =os.path.abspath(os.path.join(script_dir,"bounding_boxes"))
        if not os.path.exists(bounding_box_dir):
            os.mkdir(bounding_box_dir)
        # load different csv files depending on location given
        if location == 'usa':
            csv_file='usa_shorelines_bounding_boxes.csv'
        elif location == 'world':
            csv_file='world_shorelines_bounding_boxes.csv'
        # Create full path to csv file    
        shoreline_csv= os.path.join(bounding_box_dir,csv_file)
        total_bounds_df=pd.read_csv(shoreline_csv)
        # print("total_bounds_df",total_bounds_df)
        
        total_bounds_df.index=total_bounds_df["filename"]
        if 'filename' in total_bounds_df.columns:
            total_bounds_df.drop("filename",axis=1, inplace=True)
        return total_bounds_df 
            
    def make_coastsat_compatible(shoreline_in_roi:gpd.geodataframe)->np.ndarray:
        """Return the shoreline_in_roi as an np.array in the form: 
            array([[lat,lon,0],[lat,lon,0],[lat,lon,0]....])

        Args:
            shoreline_in_roi (gpd.geodataframe): clipped portion of shoreline withinv a roi

        Returns:
            np.ndarray: shorelines in the form: 
                array([[lat,lon,0],[lat,lon,0],[lat,lon,0]....])
        """
        # Then convert the shoreline to lat,lon tuples for CoastSat
        shorelines = []
        for k in shoreline_in_roi['geometry'].keys():
            #For each linestring portion of shoreline convert to lat,lon tuples
            shorelines.append(tuple(np.array(shoreline_in_roi['geometry'][k]).tolist()))
        # shorelines = [([lat,lon],[lat,lon],[lat,lon]),([lat,lon],[lat,lon],[lat,lon])...]
        # Stack all the tuples into a single list of n rows X 2 columns
        shorelines = np.vstack(shorelines)
        # Add third column of 0s to represent mean sea level
        shorelines = np.insert(shorelines, 2, np.zeros(len(shorelines)), axis=1)
        # shorelines = array([[lat,lon,0],[lat,lon,0],[lat,lon,0]....])
        return shorelines


