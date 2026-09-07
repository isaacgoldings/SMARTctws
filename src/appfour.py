from dash import Dash, html, dcc, callback, Output, Input, State, ctx, no_update
# to make the dash app work

import plotly.express as px
import plotly.graph_objects as go
# to make the plotly graph quick - vis on the right work

import pandas as pd
# basic

import datetime
from datetime import datetime as dt, timezone, timedelta
# make datetime work in terms of when scraped as well as querying

import webbrowser
# app will open in the default web browser

from threading import Timer
# these above two just used to make app start automatically

# Try to import the real functions to make the app work. 
# If they are not available (e.g. during local dev),
# fall back to demo placeholders so the app still runs.
# Keeping these in for any future development in case something breaks and I need to fall back on them

try:
    from app_functions.generate_sql_query import generate_query_and_params
    print("generate_query_and_params successfully imported")
except Exception as e:
    generate_query_and_params = None
    _IMPORT_GENERATE_QUERY_ERROR = str(e)

try:
    from db_code.interact_db import read_db
    print("interact_db successfully imported")
except Exception as e:
    read_db = None
    _IMPORT_READ_DB_ERROR = str(e)

try:
    from app_functions.webscraping import do_webscrape
    print("do_webscrape successfully imported")
except Exception as e:
    do_webscrape = None
    _IMPORT_WEBSCRAPE_ERROR = str(e)

try:
    from db_code.interact_db import add_new
    print("add_new successfully imported")
except Exception as e:
    add_new = None
    _IMPORT_ADD_NEW_ERROR = str(e)

# -------------------------
# Helper helpers & fallback demo data
# -------------------------
def df_to_options(df, label_col, value_col):
    return [{'label': row[label_col], 'value': row[value_col]} for _, row in df.iterrows()]

def _demo_species_df():
    return pd.DataFrame({
        'species_name': [f'Sp{i}' for i in range(1, 6)],
        'species_id': [101, 102, 103, 104, 105]
    })

def _demo_serials_df():
    # column named 'serialId' in demo to mirror the expected read_db output for serials
    return pd.DataFrame({'serialId': [f'S{n:02d}' for n in range(1, 21)]})

# -------------------------
# Integrations: run_all_update_funcs -> queries the DB for everything needed to populate the querying fields, as well as last scraped
# -------------------------
def run_all_update_funcs():
    """
    This function runs at startup and returns:
     - species_df: DataFrame with at least columns ['species_name', 'species_id'] to populate species names
     - observations_df: DataFrame used to populate serial dropdown (expected to contain serial IDs)
    """
    sql_serials = "SELECT serialId FROM tAnimal"   # expect column 'serialId' is in tAnimal (see ERD)
    sql_species = "SELECT * FROM tSpecies"   # expects columns 'species_id' and 'species_name'

    # Fallbacks, try read_db but if for whatever reason it doesn't work do fallback
    if read_db is not None:
        try:
            serials_df = read_db(sql_serials)
            species_df = read_db(sql_species)
        except Exception as e:
            species_df = _demo_species_df()
            serials_df = _demo_serials_df()
    else:
        species_df = _demo_species_df()
        serials_df = _demo_serials_df()

    return {'species_df': species_df, 'observations_df': serials_df}

# -------------------------
# SQL helpers (unchanged)
# -------------------------
def build_sql_and_params_from_selections(species_wanted, 
                                         serialId_wanted, 
                                         datemin, 
                                         datemax,
                                         lat_min,
                                         lat_max,
                                         lon_min,
                                         lon_max):
    
    # THIS WHOLE IF IS A FALLBACK
    if generate_query_and_params is None:
        where_clauses = []
        params = {}
        if species_wanted is not None:
            where_clauses.append("species_id IN %(species)s")
            params['species'] = tuple(species_wanted)
        if serialId_wanted is not None:
            where_clauses.append("serialId IN %(serial)s")
            params['serial'] = tuple(serialId_wanted)
        if datemin is not None:
            where_clauses.append("date >= %(datemin)s")
            params['datemin'] = datemin.isoformat()
        if datemax is not None:
            where_clauses.append("date <= %(datemax)s")
            params['datemax'] = datemax.isoformat()
        if lat_min is not None:
            where_clauses.append("latitude >= %(lat_min)s")
            params['lat_min'] = lat_min
        if lat_max is not None:
            where_clauses.append("latitude <= %(lat_max)s")
            params['lat_max'] = lat_max
        if lon_min is not None:
            where_clauses.append("longitude >= %(lon_min)s")
            params['lon_min'] = lon_min
        if lon_max is not None:
            where_clauses.append("longitude <= %(lon_max)s")
            params['lon_max'] = lon_max
        where = " AND ".join(where_clauses) if where_clauses else "1=1"
        sql = f"SELECT * FROM observations WHERE {where};"
        return sql, params
    # ELSE if it is working as intended
    else:
        return generate_query_and_params(
            serialIds=serialId_wanted,
            species_ids=species_wanted,
            datemin=datemin,
            datemax=datemax,
            lat_min=lat_min,
            lat_max=lat_max,
            lon_min=lon_min,
            lon_max=lon_max
        )

# Includes fallbacks but basically try and do read_db or account for several ways it could go wrong
def execute_sql(sql, params):
    if read_db is None:
        return pd.DataFrame()
    try:
        return read_db(sql, params)
    except TypeError:
        return read_db(sql)
    except Exception:
        return pd.DataFrame()

# Blank initial figure to show 1. initially or 2. if the query results in no data
def blank_map():
    df_empty = pd.DataFrame({'lat': [], 'lon': []})
    fig = px.scatter_map(df_empty, lat='lat', lon='lon', title='No data')
    fig.update_layout(
        map_style='open-street-map',
        map_center={"lat": -1.9, "lon": 34.8108},
        map_zoom=8,
        paper_bgcolor="#eef4ab"

    )
    return fig

# ---------------------------------------------------------
# APPLICATION SETUP
# ---------------------------------------------------------
app = Dash(__name__)
server = app.server

# ------------------------------
# RUN AT APP STARTUP (module import time)
# ------------------------------

startup_results = run_all_update_funcs()
# returns two dataframes

_startup_species_df = startup_results.get('species_df', pd.DataFrame(columns=['species_name', 'species_id']))
_startup_observations_df = startup_results.get('observations_df', pd.DataFrame())
# get those two dataframes

# Prepare initial store data
initial_species_store = _startup_species_df.to_dict(orient='records')
initial_observations_store = _startup_observations_df.to_dict(orient='records')

def get_last_scraped():
    # Query the DB once during app startup
    try:
        df = read_db("SELECT MAX(last_scraped) AS last FROM tAnimal")
        if df.iloc[0]["last"] is not None:
            return df.iloc[0]["last"]
    except:
        pass
    return "Unknown"

initial_last_scraped = get_last_scraped()

# ------------------------------
# LAYOUT
# ------------------------------
app.layout = html.Div([

    # Theme link (we will update its href dynamically with a callback)
    html.Link(id='theme-link', rel='stylesheet', href='/assets/theme_default.css'),

    # Stores: persist "in-memory" objects
    dcc.Store(id='store-species-df', data=initial_species_store),
    dcc.Store(id='store-observations-df', data=initial_observations_store),
    dcc.Store(id='store-sql', data=None),
    dcc.Store(id='store-params', data=None),
    dcc.Store(id='store-results-df', data=None),
    dcc.Store(id='store-last-scraped', data=initial_last_scraped),

    html.H1('Serengeti Mammal Analysis & Research Tool', style={'textAlign': 'center'}),

    html.Div([
        # LEFT: controls column
        html.Div([
            html.H3("Query Controls"),
            html.Div("Selecting none will return all possible values"),
            html.Br(),
            html.Label("Species (multi-select)"),
            dcc.Dropdown(
                id='dropdown-species',
                options=df_to_options(_startup_species_df, 'species_name', 'species_id'),
                multi=True,
                placeholder='Select species...'
            ),

            html.Br(),
            html.Label("Serial ID (multi-select)"),
            dcc.Dropdown(
                id='dropdown-serial',
                options=[{'label': s, 'value': s} for s in sorted(_startup_observations_df['serialId'].unique())] if not _startup_observations_df.empty else [],
                multi=True,
                placeholder='Select serial IDs...'
            ),
            html.Button("Select all serials", id='btn-select-all-serials', n_clicks=0),

            html.Br(), html.Br(),
            html.Label("Minimum date (Midnight this day)"),
            html.Br(),html.Br(),
            dcc.DatePickerSingle(
                id='date-min',
                placeholder='Pick min date',
                display_format='YYYY-MM-DD'
            ),
            html.Br(),html.Br(),
            html.Label("Maximum date (Midnight this day)"),
            html.Br(),html.Br(),
            dcc.DatePickerSingle(
                id='date-max',
                placeholder='Pick max date',
                display_format='YYYY-MM-DD'
            ),
            html.Br(), html.Br(),

            html.Div([
               html.Label("Latitude Min"),
               dcc.Input(id='lat-min', type='number', placeholder='Min Latitude', style={'width': '100%'}),


               html.Label("Latitude Max"),
               dcc.Input(id='lat-max', type='number', placeholder='Max Latitude', style={'width': '100%'}),


               html.Label("Longitude Min"),
               dcc.Input(id='lon-min', type='number', placeholder='Min Longitude', style={'width': '100%'}),


               html.Label("Longitude Max"),
               dcc.Input(id='lon-max', type='number', placeholder='Max Longitude', style={'width': '100%'}),
           ], style={'display': 'grid', 'gridTemplateColumns': '1fr 1fr', 'gap': '10px', 'marginBottom': '20px'}),


           # Red warning message
           html.Div(
               "🐾 Warning: Setting min/max latitude or longitude may cut off parts of an animal's path. "
               "The points on the map may be misleading if your range intersects the animals' paths.🐾",
               style={'color': 'red', 'marginBottom': '10px', 'font-weight':'bold'}
           ),

            html.Button("Generate query", id='btn-generate-query', n_clicks=0),
            # Toggle to show/hide SQL
            dcc.Checklist(
                id='chk-show-sql',
                options=[{'label': 'Show SQL', 'value': 'show'}],
                value=[],
                style={'display': 'inline-block', 'marginLeft': '10px'}
            ),
            html.Div(id='sql-display', style={'fontSize': '12px', 'marginLeft': '10px', 'display': 'inline-block', 'verticalAlign': 'middle', 'maxWidth': '400px', 'whiteSpace': 'pre-wrap'}),
            html.Br(), html.Br(),

            html.Button("Run query", id='btn-run-query', n_clicks=0, disabled=True),

            html.Hr(),
            html.Label("Theme"),
            dcc.RadioItems(
                id='theme-selector',
                options=[
                    {'label': 'Default', 'value': 'default'},
                    {'label': 'Dark', 'value': 'dark'},
                    {'label': 'Blue', 'value': 'blue'}
                ],
                value='default',
                labelStyle={'display': 'inline-block', 'marginRight': '10px'}
            ),

        ], style={'width': '28%', 'display': 'inline-block', 'verticalAlign': 'top', 'padding': '10px', 'boxSizing': 'border-box'}),

        # RIGHT: webscrape button, figure, export button
        html.Div([
            html.Div([
                html.Span(id='display-last-scraped', style={'marginRight': '20px', 'marginLeft': '20px', 'text-align':'left'}),
                dcc.Loading(
                    id='webscrape-loading',
                    type='circle',
                    children=html.Button("Webscrape", id='btn-webscrape', n_clicks=0, style={'marginRight': '20px'})
                ),
                # Removed "Update current" button per request
            ], style={'textAlign': 'right', 'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center', 'gap': '10px'}),


            html.Div([
                dcc.Graph(
                    id='graph-content',
                    figure=blank_map(),
                    style={'height': '100%', 'width': '100%'}
                )],
                style={
                'height': '90vh',
                'width': '100%',
                'overflow': 'hidden'
                }),


            html.Br(),
            html.Div([
                html.Button("Export CSV (current results)", id='btn-export-csv', n_clicks=0),
                dcc.Download(id='download-results-csv')
            ], style={'textAlign': 'right', 'marginTop': '10px'})
        ], style={'width': '68%', 'display': 'inline-block', 'padding': '10px', 'boxSizing': 'border-box', 'verticalAlign': 'top'})
    ], style={'width': '100%', 'display': 'flex', 'justifyContent': 'space-between'}),
    html.Div([
        html.P("Data sourced from serengeti-tracker.org. Developed by Christopher Tillotson and William Stanziano, Fall 2025."),
    ], style={'marginTop': '10px', 'fontStyle': 'italic'})
],
    # Basic inline fallback styling (themes live in CSS files)
    style={
    'fontFamily': 'Arial, sans-serif',
    'padding': '0',
    'margin': '0',
    }
)
# End layout

# ---------------------------------------------------------
# CALLBACKS
# ---------------------------------------------------------

# When species or observations store changes, refresh dropdown options for species and serial dropdown
@callback(
    Output('dropdown-species', 'options'),
    Output('dropdown-serial', 'options'),
    Input('store-species-df', 'data'),
    Input('store-observations-df', 'data')
)
def refresh_dropdown_options(species_store, observations_store):
    species_df = pd.DataFrame(species_store) if species_store else pd.DataFrame(columns=['species_name', 'species_id'])
    obs_df = pd.DataFrame(observations_store) if observations_store else pd.DataFrame()

    species_options = df_to_options(species_df, 'species_name', 'species_id') if not species_df.empty else []
    if not obs_df.empty:
        if 'serialId' in obs_df.columns:
            serial_list = sorted(obs_df['serialId'].astype(str).unique())
        elif 'serialId' in obs_df.columns:
            serial_list = sorted(obs_df['serialId'].astype(str).unique())
        else:
            serial_list = sorted(obs_df[obs_df.columns[0]].astype(str).unique())
        serial_options = [{'label': s, 'value': s} for s in serial_list]
    else:
        serial_options = []
    return species_options, serial_options


# Select all serials button: set dropdown-serial value to all available options
@callback(
    Output('dropdown-serial', 'value'),
    Input('btn-select-all-serials', 'n_clicks'),
    State('dropdown-serial', 'options'),
    prevent_initial_call=True
)
def select_all_serials(n_clicks, options):
    if not options:
        return no_update
    all_values = [opt['value'] for opt in options]
    return all_values


# Generate query button: read current selections and create SQL + params via your function
# Also hide/show SQL display depending on checkbox
@callback(
    Output('store-sql', 'data'),
    Output('store-params', 'data'),
    Output('sql-display', 'children'),
    Input('btn-generate-query', 'n_clicks'),
    Input('chk-show-sql', 'value'),
    State('dropdown-species', 'value'),
    State('dropdown-serial', 'value'),
    State('date-min', 'date'),
    State('date-max', 'date'),
    State('dropdown-species', 'options'),
    State('dropdown-serial', 'options'),
    State('lat-min', 'value'),
    State('lat-max', 'value'),
    State('lon-min', 'value'),
    State('lon-max', 'value'),
    prevent_initial_call=False
)
def on_generate_query(n_clicks, show_sql_vals, species_selected, serial_selected, date_min, date_max, species_options, serial_options,
                      lat_min, lat_max, lon_min, lon_max):
    all_species_values = [opt['value'] for opt in species_options] if species_options else []
    all_serial_values = [opt['value'] for opt in serial_options] if serial_options else []

    if not species_selected or set(species_selected) == set(all_species_values):
        species_wanted = None
    else:
        species_wanted = list(species_selected)

    if not serial_selected or set(serial_selected) == set(all_serial_values):
        serialId_wanted = None
    else:
        serialId_wanted = list(serial_selected)

    datemin = pd.to_datetime(date_min).to_pydatetime() if date_min else None
    datemax = pd.to_datetime(date_max).to_pydatetime() if date_max else None

    sql, params = build_sql_and_params_from_selections(
       species_wanted,
       serialId_wanted,
       datemin,
       datemax,
       lat_min=lat_min,
       lat_max=lat_max,
       lon_min=lon_min,
       lon_max=lon_max
   )


    show_sql = 'show' in (show_sql_vals or [])
    sql_text = str(sql) + "\n Params: \n" + str(params) if (show_sql and sql) else ""

    return sql, params, sql_text


# Enable/disable Run Query button depending on whether SQL exists in memory
@callback(
    Output('btn-run-query', 'disabled'),
    Input('store-sql', 'data')
)
def toggle_run_button(sql):
    if not sql:
        return True
    return False


# Run query button: run the query (using read_db) and store result df and return a map figure
@callback(
    Output('store-results-df', 'data'),
    Output('graph-content', 'figure'),
    Input('btn-run-query', 'n_clicks'),
    State('store-sql', 'data'),
    State('store-params', 'data'),
    prevent_initial_call=True
)
def on_run_query(n_clicks, sql, params):
    df = execute_sql(sql, params)
    if df is None:
        df = pd.DataFrame()
    results_data = df.to_dict(orient='records')
    fig = build_map_figure_from_df(df)
    return results_data, fig


# Display "Last scraped:" in three time zones
@callback(
    Output('display-last-scraped', 'children'),
    Input('store-last-scraped', 'data')
)
def show_last_scraped(last_scraped):
    if not last_scraped:
        return "Last scraped: Unknown"
    # last_scraped may be string or datetime-like; try to parse
    try:
        parsed = pd.to_datetime(last_scraped)
        # Make timezone-aware assuming stored as UTC if naive (common for DB timestamps)
        if parsed.tzinfo is None:
            parsed = parsed.tz_localize('UTC')
    except Exception:
        # If cannot parse, just show raw string
        return f"Last scraped: {last_scraped}"

    # Define timezones
    tz_utc = timezone.utc # time the data is stored in
    tz_eat = timezone(timedelta(hours=3))   # East Africa Time UTC+3
    tz_est = timezone(timedelta(hours=-5))  # Eastern Standard Time UTC-5

    # fmt = "%Y-%m-%d %H:%M:%S %Z%z"

    try:
        # Convert to the three zones
        zulu = parsed.astimezone(tz_utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        eat = parsed.astimezone(tz_eat).strftime("%Y-%m-%d %H:%M:%S UTC+03")
        est = parsed.astimezone(tz_est).strftime("%Y-%m-%d %H:%M:%S UTC-05")
        return html.Div([
            html.Div("Last scraped:"),
            html.Div(f"| {eat} Eastern Africa Time"),
            html.Div(f"| {est} Eastern Standard Time"),
            html.Div(f"| {zulu} Zulu (GMT) Time"),
            html.Div("Should be done at least every 3 months for accurate data")
        ])
    except Exception:
        # fallback
        return f"Last scraped: {str(last_scraped)}"


# Webscrape button: disable while running, change text, run scraper and add_new, then update stores
@callback(
    Output('store-species-df', 'data'),
    Output('store-observations-df', 'data'),
    Output('store-last-scraped', 'data'),
    Output('btn-webscrape', 'disabled'),
    Output('btn-webscrape', 'children'),
    Input('btn-webscrape', 'n_clicks'),
    prevent_initial_call=True
)
def on_webscrape(n_clicks):
    # Immediately set button disabled and text — Dash will send these outputs once the callback completes.
    # If webscrape function missing, just return no_update for stores and re-enable button
    if do_webscrape is None or add_new is None:
        print("Webscraping or add_new function unavailable.")
        # still run run_all_update_funcs to refresh from DB if possible
        results = run_all_update_funcs()
        species_df = results.get('species_df', pd.DataFrame(columns=['species_name', 'species_id']))
        observations_df = results.get('observations_df', pd.DataFrame())
        # try to get last_scraped from DB
        try:
            last_df = read_db("SELECT last_scraped FROM tAnimal")
            last_scraped = last_df['last_scraped'].max()
            last_scraped = str(last_scraped) if last_scraped is not None else "Unknown"
        except Exception:
            last_scraped = "Unknown"
        return (species_df.to_dict(orient='records'),
                observations_df.to_dict(orient='records'),
                last_scraped,
                False,
                "Webscrape")

    # If real webscrape available, run it (synchronously)
    try:
        # Run webscrape; depending on your implementation, this could take time.
        # The callback will run synchronously on the server process.
        df_new = do_webscrape()
        add_new(df_new)
    except Exception as e:
        print("Webscrape error:", e)

    # After webscraping finishes, re-run the update functions 
    results = run_all_update_funcs()
    species_df = results.get('species_df', pd.DataFrame(columns=['species_name', 'species_id']))
    observations_df = results.get('observations_df', pd.DataFrame())

    # Try to get last_scraped timestamp from DB
    try:
        last_df = read_db("SELECT last_scraped FROM tAnimal")
        last_scraped = last_df['last_scraped'].max()
        last_scraped = str(last_scraped) if last_scraped is not None else "Unknown"
    except Exception:
        last_scraped = "Unknown"

    # Return stores + re-enabled button + normal label
    return (species_df.to_dict(orient='records'),
            observations_df.to_dict(orient='records'),
            last_scraped,
            False,
            "Webscrape")


def build_map_figure_from_df(df):
    """
    Build a map figure that:
     - Plots all points (latitude/longitude) colored by serialId
     - Links points for the same serialId in chronological order
     - Shows hovertext with serialId, date, latitude, longitude, species_name
    Implementation note:
     - Uses one trace per serial with mode='lines+markers' so legend isolation (double-click) hides both markers and lines together
     - Markers and lines will share the same color per trace (automatic Plotly coloring)
    """
    if df is None or df.empty:
        return blank_map()

    df2 = df.copy()

    # Ensures works with isoformat
    # Rows can have mixed precision (some with fractional seconds / trailing 'Z',
    # some without), so parse as ISO8601 and normalize to UTC instead of letting
    # pandas infer a single format from the first value.
    df2['date'] = pd.to_datetime(df2['date'], format='ISO8601', utc=True)

    # center map
    # NOTE to future editors
    # Override here is a design choice. Remove to allow default logic,
    # Which is to center over queried area.
    try:
        center_lat = df2['latitude'].astype(float).mean()
        center_lon = df2['longitude'].astype(float).mean()
        map_center = {"lat": center_lat, "lon": center_lon}

        ## OVERRIDE
        # override to manual center if desired:
        map_center = {"lat": -1.9, "lon": 34.81076841740793}
        ## /OVERRIDE

    except Exception:
        map_center = {"lat": -1.9, "lon": 34.81076841740793}

    fig = go.Figure()

    # iterate by serialId and create one trace per serial (lines+markers)
    for sid, group in df2.groupby('serialId'):
        g = group.sort_values('date')
        lat_list = g['latitude'].astype(float).tolist()
        lon_list = g['longitude'].astype(float).tolist()
        hover_texts = []
        for _, row in g.iterrows():
            dt_str = row['date'].isoformat() if pd.notnull(row['date']) else ''
            species_str = row['species_name'] if 'species_name' in row and pd.notnull(row['species_name']) else ''
            hover_texts.append(
                f"serialId: {sid}<br>date: {dt_str}<br>lat: {row['latitude']}<br>lon: {row['longitude']}<br>species_name: {species_str}"
            )

        # mode 'lines+markers' will draw either markers only (if single point) or both
        fig.add_trace(go.Scattermap(
            lat=lat_list,
            lon=lon_list,
            mode='lines+markers',
            name=str(sid),           # legend entry per serial
            legendgroup=str(sid),    # group traces (not strictly necessary here but kept consistent)
            hoverinfo='text',
            hovertext=hover_texts,
            marker=dict(size=8),
            line=dict(width=2),
            showlegend=True,
        ))

    # Layout using mapb (open-street-map style)
    fig.update_layout(
        map_style='open-street-map',
        map_center=map_center,
        map_zoom=7.5,
        margin={'l':0, 'r':0, 'b':0, 't':50},
        title='Observations map (points linked by serialId in time order)',
        paper_bgcolor="#eef4ab"
    )

    return fig


# Export CSV: create and send CSV from store-results-df
@callback(
    Output('download-results-csv', 'data'),
    Input('btn-export-csv', 'n_clicks'),
    State('store-results-df', 'data'),
    prevent_initial_call=True
)
def export_csv(n_clicks, results_store):
    if not results_store:
        return no_update
    df = pd.DataFrame(results_store)
    return dcc.send_data_frame(df.to_csv, filename=f'results_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.csv', index=False)


# Theme selector: update the CSS href to switch themes 
# assets must contain the files
@callback(
    Output('theme-link', 'href'),
    Input('theme-selector', 'value')
)
def switch_theme(theme_value):
    if theme_value == 'dark':
        return '/assets/theme_dark.css'
    if theme_value == 'blue':
        return '/assets/theme_blue.css'
    return '/assets/theme_default.css'


# ---------------------------------------------------------
# RUN APP
# ---------------------------------------------------------
if __name__ == '__main__':
    port = 8050
    address = f"http://localhost:{port}"

    # Open the browser after Dash starts
    Timer(3, lambda: webbrowser.open(address)).start()

    app.run(debug=False, port=port)
