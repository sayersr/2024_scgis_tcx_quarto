from shiny import App, ui, render, reactive
import gpxpy
import gpxpy.gpx
import xml.etree.ElementTree as ET
import matplotlib.pyplot as plt
import datetime
import io
import folium

# Define a list of contrasting colors
CONTRASTING_COLORS = ['#FF0000', '#00FF00', '#0000FF', '#FF00FF', '#00FFFF', '#FFFF00', '#800000', '#008000', '#000080', '#800080']

app_ui = ui.page_fluid(
    ui.panel_title("TCX Data Viewer"),
    ui.layout_sidebar(
        ui.sidebar(
            ui.input_file("tcx_files", "Upload TCX file(s)", accept=[".tcx"], multiple=True),
            ui.output_ui("file_info"),
        ),
        ui.column(6,
            ui.output_ui("map_output"),
        ),
        ui.column(6,
            ui.output_plot("heart_rate_plot"),
        ),
    )
)

def server(input, output, session):
    
    tcx_data = reactive.Value({})
    
    @reactive.Effect
    @reactive.event(input.tcx_files)
    def _():
        files = input.tcx_files()
        if files is None:
            tcx_data.set({})
            return
        
        processed_data = {}
        for i, file in enumerate(files):
            file_content = file["datapath"]
            try:
                with open(file_content, "r") as f:
                    tcx_content = f.read()
                gpx, heart_rates, start_time, duration = convert_tcx_to_gpx(tcx_content)
                max_hr = max(heart_rates) if heart_rates else 0
                processed_data[file["name"]] = {
                    "gpx": gpx,
                    "heart_rates": heart_rates,
                    "start_time": start_time,
                    "duration": duration,
                    "max_hr": max_hr,
                    "color": CONTRASTING_COLORS[i % len(CONTRASTING_COLORS)]
                }
            except Exception as e:
                print(f"Error processing TCX data for {file['name']}: {str(e)}")
                processed_data[file["name"]] = {"error": f"Error processing TCX data: {str(e)}"}
        
        tcx_data.set(processed_data)

    @output
    @render.ui
    def file_info():
        data = tcx_data.get()
        if not data:
            return "Please upload TCX file(s)."
        
        info_html = "<h3>Data Information:</h3>"
        for filename, file_data in data.items():
            if "error" in file_data:
                info_html += f"<p><strong>{filename}:</strong> Error: {file_data['error']}</p>"
            else:
                info_html += f"<p><strong>{filename}:</strong><br>"
                info_html += f"Date: {file_data['start_time'].strftime('%Y-%m-%d %H:%M:%S')}<br>"
                info_html += f"Duration: {str(file_data['duration']).split('.')[0]}<br>"
                info_html += f"Maximum Heart Rate: {file_data['max_hr']} bpm</p>"
        
        return ui.HTML(info_html)

    @output
    @render.ui
    def map_output():
        data = tcx_data.get()
        if not data:
            return "No map data available"
        
        # Create a folium map centered on the first point of the first file
        first_file = next(iter(data.values()))
        if "error" in first_file:
            return "No valid map data available"
        
        first_points = get_points(first_file['gpx'])
        if not first_points:
            return "No valid GPS points found"
        
        m = folium.Map(location=first_points[0], zoom_start=12)
        
        for filename, file_data in data.items():
            if "error" not in file_data:
                points = get_points(file_data['gpx'])
                if points:
                    # Add the track as a polyline
                    folium.PolyLine(points, color=file_data['color'], weight=2.5, opacity=0.8, popup=filename).add_to(m)
                    
                    # Add markers for start and end points
                    folium.Marker(points[0], popup=f"Start - {filename}", icon=folium.Icon(color='green', icon='play')).add_to(m)
                    folium.Marker(points[-1], popup=f"End - {filename}", icon=folium.Icon(color='red', icon='stop')).add_to(m)
        
        # Convert the map to HTML
        map_html = m._repr_html_()
        
        # Wrap the map HTML in a div with a fixed height and width
        return ui.HTML(f"<div style='height: 400px; width: 100%;'>{map_html}</div>")

    @output
    @render.plot
    def heart_rate_plot():
        data = tcx_data.get()
        if not data:
            return None
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        for filename, file_data in data.items():
            if "error" not in file_data:
                time_labels = [str(datetime.timedelta(seconds=s)) for s in range(int(file_data['duration'].total_seconds()) + 1)]
                ax.plot(time_labels[:len(file_data['heart_rates'])], file_data['heart_rates'], color=file_data['color'], label=filename)
        
        ax.set_xlabel("Time (hours:minutes:seconds)")
        ax.set_ylabel("Heart Rate (bpm)")
        ax.set_title("Heart Rate Over Time")
        
        plt.xticks(rotation=45, ha='right')
        
        # Show only a subset of x-axis labels to avoid overcrowding
        num_ticks = 10
        tick_indices = [i for i in range(0, len(time_labels), len(time_labels) // num_ticks)]
        plt.xticks(tick_indices, [time_labels[i] for i in tick_indices])
        
        plt.legend()
        plt.tight_layout()
        return fig

def convert_tcx_to_gpx(tcx_content):
    def parse_xml(content):
        return ET.fromstring(content)

    try:
        tcx_root = parse_xml(tcx_content)
    except ET.ParseError as e:
        raise ValueError(f"Unable to parse TCX data. Error: {str(e)}. Data starts with: {tcx_content[:100]}")

    gpx = gpxpy.gpx.GPX()
    track = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(track)
    segment = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(segment)

    namespace = {'ns': 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2'}
    
    heart_rates = []
    start_time = None
    end_time = None
    
    for trackpoint in tcx_root.findall('.//ns:Trackpoint', namespace):
        time = trackpoint.find('ns:Time', namespace)
        lat = trackpoint.find('ns:Position/ns:LatitudeDegrees', namespace)
        lon = trackpoint.find('ns:Position/ns:LongitudeDegrees', namespace)
        hr = trackpoint.find('ns:HeartRateBpm/ns:Value', namespace)
        
        if time is not None:
            current_time = datetime.datetime.fromisoformat(time.text)
            if start_time is None:
                start_time = current_time
            end_time = current_time
        
        if lat is not None and lon is not None:
            point = gpxpy.gpx.GPXTrackPoint(
                latitude=float(lat.text),
                longitude=float(lon.text)
            )
            segment.points.append(point)
        
        if hr is not None:
            heart_rates.append(int(hr.text))

    if not segment.points:
        raise ValueError("No valid GPS points found in the TCX data")

    duration = end_time - start_time if start_time and end_time else datetime.timedelta()
    return gpx, heart_rates, start_time, duration

def get_points(gpx):
    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points.append((point.latitude, point.longitude))
    return points

app = App(app_ui, server)
