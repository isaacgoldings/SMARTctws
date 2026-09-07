# imports
from db_code.base_db import BaseDB

from datetime import datetime, timezone

import os
import sqlite3
import numpy as np
import pandas as pd

class CWFACDB(BaseDB):
    
    '''
    This class should extend BaseDB by adding
    functionality specific to the Serengeti data.
    '''
   
    def __init__(self,
                 path: str,
                 create: bool = False,
                ): # need to include this and then call super() to get init for the parent class
        super().__init__(path, create)
        return

    def _create_tables(self) -> None:

        print("creating tables")
        sql = """
            CREATE TABLE tSpecies ( 
                species_id INTEGER PRIMARY KEY, -- supposedly, AUTOINCREMENT not needed here because species_id auto created by sqlite
                species_name TEXT NOT NULL UNIQUE COLLATE NOCASE
            )
            ;"""
        self.run_action(sql)
        
        sql = """
            CREATE TABLE tAnimal (
                serialId TEXT PRIMARY KEY,
                species_id INTEGER NOT NULL REFERENCES tSpecies(species_id),
                first_scraped TIMESTAMP,
                last_scraped TIMESTAMP
            )
            ;"""
        self.run_action(sql)        

        sql = """
            CREATE TABLE tObservations (
                serialId TEXT NOT NULL REFERENCES tAnimal(serialId),
                date TIMESTAMP,
                collarId TEXT,
                latitude FLOAT, -- chat recommended either geography or geometry(Point, 4326), or as DECIMAL(9,6) but keeping float for now
                longitude FLOAT,
                positionId TEXT,
                PRIMARY KEY (serialId, date)
            )
            ;"""
        self.run_action(sql)   
        
        return

    def _load_data(self, df: pd.DataFrame) -> None:
        """
        Load Serengeti data into:
            tSpecies, tAnimal, tObservations
        following foreign key constraints and conflict rules.
        """

        print("loading data")

        now = datetime.now(timezone.utc).isoformat()

        # ---------------------------------------------------------
        # 1. tSpecies: Insert species if it doesn't already exist
        # ---------------------------------------------------------
        # Ensure 'unknown' species exists
        sql_insert_species = """
            INSERT INTO tSpecies (species_name)
            VALUES (:species_name)
            ON CONFLICT(species_name) DO NOTHING;
        """
        sql_select_species_id = """
            SELECT species_id
            FROM tSpecies
            WHERE species_name = :species_name;
        """

        species_to_id = {}

        # Insert all unique species in the DataFrame
        species_list = [s for s in df["species"].dropna().str.strip() if s]
        species_list.append("unknown")
        for sp in set(species_list): 
            # basically a convoluted way to get all the species including unknown always
            self.run_action(sql_insert_species, {"species_name": sp}, keep_open=True, commit = True)
            result = self.run_query(sql_select_species_id, {"species_name": sp}, keep_open = True)
            species_to_id[sp] = result.iloc[0]["species_id"]

        # ---------------------------------------------------------
        # 2. tAnimal: Ensure animals exist and update last_scraped
        # ---------------------------------------------------------
        sql_select_animal = """
            SELECT a.species_id
            FROM tAnimal a
            WHERE a.serialId = :serialId;
        """

        sql_update_animal_last = """
            UPDATE tAnimal
            SET last_scraped = :now
            WHERE serialId = :serialId;
        """

        sql_update_animal_species = """
            UPDATE tAnimal
            SET species_id = :new_species_id
            WHERE serialId = :serialId;
        """

        sql_insert_animal = """
            INSERT INTO tAnimal (serialId, species_id, first_scraped, last_scraped)
            VALUES (:serialId, :species_id, :now, :now);
        """

        sql_get_species_name = """
            SELECT species_name 
            FROM tSpecies 
            WHERE species_id = :species_id;
        """

        unique_animals = df[["serialId", "species"]].drop_duplicates()

        for _, row in unique_animals.iterrows():
            serialId = row["serialId"]
            incoming_species = row["species"]
            incoming_species_id = species_to_id.get(incoming_species, species_to_id["unknown"])

            existing = self.run_query(sql_select_animal, {"serialId": serialId}, keep_open = True)

            if existing.empty:
                # New animal → insert
                self.run_action(sql_insert_animal,
                                {"serialId": serialId, "species_id": incoming_species_id, "now": now},
                                keep_open=True, commit = True)
            else:
                # Update last_scraped
                self.run_action(sql_update_animal_last, {"serialId": serialId, "now": now}, keep_open=True, commit = True)

                # Handle species logic
                existing_species_id = existing.iloc[0]["species_id"]
                existing_species_df = self.run_query(sql_get_species_name, {"species_id": existing_species_id}, keep_open = True)
                existing_species_name = existing_species_df.iloc[0]["species_name"]

                if incoming_species != "unknown" and existing_species_name == "unknown":
                    # Upgrade unknown → real species
                    self.run_action(sql_update_animal_species,
                                    {"serialId": serialId, "new_species_id": incoming_species_id},
                                    keep_open=True, commit = True)
                # Otherwise: do nothing to species

        # ---------------------------------------------------------
        # 3. tObservations: Insert only if (serialId, date) not present
        # ---------------------------------------------------------
        sql_select_obs = """
            SELECT 1 FROM tObservations
            WHERE serialId = :serialId AND date = :date;
        """

        sql_insert_obs = """
            INSERT INTO tObservations (serialId, date, collarId, latitude, longitude, positionId)
            VALUES (:serialId, :date, :collarId, :latitude, :longitude, :positionId);
        """

        for _, row in df.iterrows():
            params = {
                "serialId": row["serialId"],
                "date": row["date"],  # already ISO string
                "collarId": row["collarId"],
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "positionId": row["positionId"],
            }

            df_obs_exist = self.run_query(sql_select_obs,
                                    {"serialId": params["serialId"],
                                     "date": params["date"]}, keep_open = True)

            if df_obs_exist.empty:
                self.run_action(sql_insert_obs, params, keep_open=True)

        self._commit_and_close()
        return