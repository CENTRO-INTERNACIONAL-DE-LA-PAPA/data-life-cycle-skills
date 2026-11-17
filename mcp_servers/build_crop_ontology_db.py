"""Build the SQLite database that crop_ontology_server.py reads.

Downloads the trait dictionary of each crop from cropontology.org (one Excel report per
crop) and writes them into one table, `ontology`, in `crop_ontology_excel.db`.

    python build_crop_ontology_db.py
"""

import io
import logging
import sqlite3
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm

# --- Configuration ---
# The output database file will be created in the same directory as this script.
DB_PATH = Path(__file__).parent / "crop_ontology_excel.db"

# The crops to load and the Crop Ontology report of each one.
CSV_DATA = """crop,report_url
Apple,"https://cropontology.org/report/CO_370"
Bambara groundnut,"https://cropontology.org/report/CO_366"
Banana,"https://cropontology.org/report/CO_325"
Barley,"https://cropontology.org/report/CO_323"
Barley Trait POLAPGEN Ontology,"https://cropontology.org/report/POLAPGEN_BARLEY"
Beet Ontology,"https://cropontology.org/report/CO_333"
Blueberry,"https://cropontology.org/report/CO_371"
Brachiaria,"https://cropontology.org/report/CO_345"
Brassica,"https://cropontology.org/report/CO_348"
Cassava,"https://cropontology.org/report/CO_334"
Castor bean,"https://cropontology.org/report/CO_347"
Chickpea,"https://cropontology.org/report/CO_338"
Coconut,"https://cropontology.org/report/CO_326"
Common bean,"https://cropontology.org/report/CO_335"
Cotton,"https://cropontology.org/report/CO_358"
Cowpea,"https://cropontology.org/report/CO_340"
Fababean,"https://cropontology.org/report/CO_365"
Groundnut,"https://cropontology.org/report/CO_337"
Lentil,"https://cropontology.org/report/CO_339"
Maize,"https://cropontology.org/report/CO_322"
Mungbean,"https://cropontology.org/report/CO_346"
Oat,"https://cropontology.org/report/CO_350"
Pearl millet,"https://cropontology.org/report/CO_327"
Pigeonpea,"https://cropontology.org/report/CO_341"
Potato,"https://cropontology.org/report/CO_330"
Quinoa Ontology,"https://cropontology.org/report/CO_367"
Red clover,"https://cropontology.org/report/CO_374"
Rice,"https://cropontology.org/report/CO_320"
Sainfoin,"https://cropontology.org/report/CO_369"
Sorghum,"https://cropontology.org/report/CO_324"
Soybean,"https://cropontology.org/report/CO_336"
Strawberry,"https://cropontology.org/report/CO_372"
Sugar Kelp trait,"https://cropontology.org/report/CO_360"
Sunflower,"https://cropontology.org/report/CO_359"
Sweet Potato,"https://cropontology.org/report/CO_331"
Vitis,"https://cropontology.org/report/CO_356"
Wheat,"https://cropontology.org/report/CO_321"
Woody Plant Ontology,"https://cropontology.org/report/CO_357"
Yam,"https://cropontology.org/report/CO_343"
"""

# Set up basic logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def normalize_colnames(df):
    """Standardizes column names to be lowercase and stripped of whitespace."""
    original_columns = df.columns
    df.columns = df.columns.str.strip().str.lower()
    return df, original_columns


def create_database_from_excel():
    """
    Downloads and processes Excel files from a list of URLs,
    analyzes column consistency, and loads the combined data into an SQLite database.
    """
    logging.info("Reading crop report URLs...")
    df_reports = pd.read_csv(io.StringIO(CSV_DATA)).dropna(subset=["report_url"])

    all_dataframes = []
    reference_columns = None
    reference_columns_normalized = None

    logging.info(f"Found {len(df_reports)} crops with report URLs to process.")

    for _, row in tqdm(
        df_reports.iterrows(),
        total=len(df_reports),
        desc="Downloading & Processing Reports",
    ):
        crop_name = row["crop"]
        url = row["report_url"]

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)

            # Use BytesIO to read the excel content from memory
            with io.BytesIO(response.content) as excel_file:
                df = pd.read_excel(excel_file, engine="openpyxl")

            df, original_cols = normalize_colnames(df)

            # Add the crop name as a new column
            df["crop"] = crop_name

            all_dataframes.append(df)

            # --- Column Consistency Check ---
            if reference_columns is None:
                reference_columns = set(original_cols)
                reference_columns_normalized = set(df.columns)
                logging.info(
                    f"'{crop_name}' used as reference. Found {len(reference_columns)} columns."
                )
                logging.info(
                    f"Reference columns: {sorted(list(reference_columns_normalized))}"
                )
            else:
                current_columns_normalized = set(df.columns)
                missing_cols = reference_columns_normalized - current_columns_normalized
                extra_cols = current_columns_normalized - reference_columns_normalized

                if missing_cols or extra_cols:
                    logging.warning(f"Column mismatch found for '{crop_name}':")
                    if missing_cols:
                        logging.warning(
                            f"  - Missing columns: {sorted(list(missing_cols))}"
                        )
                    if extra_cols:
                        logging.warning(
                            f"  - Extra columns: {sorted(list(extra_cols))}"
                        )

        except requests.exceptions.RequestException as e:
            logging.error(
                f"Could not download report for '{crop_name}'. URL: {url}. Error: {e}"
            )
        except Exception as e:
            logging.error(f"Failed to process Excel file for '{crop_name}'. Error: {e}")

    if not all_dataframes:
        logging.error("No data was successfully processed. Aborting database creation.")
        return

    # --- Consolidate and Save to SQLite ---
    logging.info("Combining all dataframes...")
    # `concat` handles missing columns by filling with NaN, which is what we want.
    final_df = pd.concat(all_dataframes, ignore_index=True)
    # Standardize column names across the final dataframe
    final_df.columns = final_df.columns.str.replace(" ", "_").str.replace(
        "[^0-9a-zA-Z_]+", "", regex=True
    )

    logging.info(f"Saving combined data to SQLite database at: {DB_PATH}")
    try:
        conn = sqlite3.connect(DB_PATH)
        # Use if_exists='replace' to overwrite the table if the script is run again
        final_df.to_sql("ontology", conn, if_exists="replace", index=False)
        conn.close()
        logging.info(
            f"✅ Success! Database '{DB_PATH.name}' created with {len(final_df)} total records."
        )
        logging.info(f"Final table columns: {sorted(final_df.columns)}")
    except Exception as e:
        logging.error(f"Failed to write to SQLite database. Error: {e}")


if __name__ == "__main__":
    create_database_from_excel()
