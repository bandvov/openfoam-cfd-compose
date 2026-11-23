#!/usr/bin/env pvpython

from paraview.simple import *
import os

# --------------------------------------------------
# Configuration
# --------------------------------------------------

CASE_FILE = os.getenv(
    "CASE_FILE",
    "/workspace/results/aircraft/case.foam"
)

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/data")

FIELD = os.getenv("FIELD", "U")
SLICE_AXIS = os.getenv("SLICE_AXIS", "z").lower()

IMAGE_WIDTH = 1920
IMAGE_HEIGHT = 1080


def log(message):
    print(message, flush=True)


def main():

    log("=== ParaView CFD visualization ===")

    # --------------------------------------------------
    # 1. Check input
    # --------------------------------------------------

    if not os.path.exists(CASE_FILE):
        raise FileNotFoundError(
            f"OpenFOAM case not found: {CASE_FILE}"
        )

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    log(f"Loading case: {CASE_FILE}")

    # --------------------------------------------------
    # 2. Load OpenFOAM results
    # --------------------------------------------------

    reader = OpenFOAMReader(
        registrationName="AircraftCFD",
        FileName=CASE_FILE
    )

    reader.MeshRegions = ["internalMesh"]
    reader.CellArrays = ["U", "p"]

    reader.UpdatePipeline()

    log("OpenFOAM case loaded")

    # --------------------------------------------------
    # 3. Select latest timestep
    # --------------------------------------------------

    times = reader.TimestepValues
    # pvpython returns a bare float when there is only one timestep
    if isinstance(times, (int, float)):
        times = [times]
    times = list(times)

    if times:
        latest_time = max(times)

        log(f"Available timesteps: {len(times)}")
        log(f"Latest timestep: {latest_time}")

        reader.UpdatePipeline(time=latest_time)

    else:
        latest_time = 0
        log("No transient timesteps found; using available fields")

    # --------------------------------------------------
    # 4. Create render view
    # --------------------------------------------------

    view = GetActiveViewOrCreate("RenderView")

    view.ViewSize = [
        IMAGE_WIDTH,
        IMAGE_HEIGHT
    ]

    view.Background = [
        0.08,
        0.09,
        0.13
    ]

    view.UseColorPaletteForBackground = 0

    # Show the latest solution. Updating the reader alone is not enough:
    # downstream filters and the screenshot use the view/animation time,
    # which otherwise stays at the first timestep.
    scene = GetAnimationScene()
    scene.UpdateAnimationUsingDataTimeSteps()
    scene.AnimationTime = latest_time
    view.ViewTime = latest_time

    # --------------------------------------------------
    # 5. Create aircraft airflow cross-section
    # --------------------------------------------------

    log("Creating airflow slice")

    slice_filter = Slice(
        registrationName="AircraftFlowSlice",
        Input=reader
    )

    slice_filter.SliceType = "Plane"

    # Aircraft coordinate system:
    # X = longitudinal
    # Y = spanwise
    # Z = vertical

    if SLICE_AXIS not in ("x", "y", "z"):
        log(f"Unknown SLICE_AXIS '{SLICE_AXIS}', using z")
        SLICE_AXIS_USED = "z"
    else:
        SLICE_AXIS_USED = SLICE_AXIS

    if SLICE_AXIS_USED == "x":
        slice_filter.SliceType.Normal = [1, 0, 0]

    elif SLICE_AXIS_USED == "y":
        slice_filter.SliceType.Normal = [0, 1, 0]

    else:
        slice_filter.SliceType.Normal = [0, 0, 1]

    slice_filter.SliceType.Origin = [0, 0, 0]

    slice_filter.UpdatePipeline(time=latest_time)

    log("Slice created")

    # --------------------------------------------------
    # 6. Display CFD results
    # --------------------------------------------------

    display = Show(
        slice_filter,
        view
    )

    display.Representation = "Surface"

    if FIELD not in ("p", "U"):
        log(f"Unknown FIELD '{FIELD}', using U")

    if FIELD == "p":

        ColorBy(
            display,
            ("CELLS", "p")
        )

        lut = GetColorTransferFunction("p")
        lut.ApplyPreset("Cool to Warm", True)

        # simpleFoam solves kinematic pressure (p/rho)
        title = "Kinematic pressure p/rho [m^2/s^2]"

        log("Displaying pressure field")

    else:

        ColorBy(
            display,
            ("CELLS", "U", "Magnitude")
        )

        lut = GetColorTransferFunction("U")
        lut.ApplyPreset("Cool to Warm", True)

        title = "Velocity magnitude [m/s]"

        log("Displaying velocity magnitude")

    display.LookupTable = lut
    display.RescaleTransferFunctionToDataRange(True, False)
    display.SetScalarBarVisibility(view, True)
    GetScalarBar(lut, view).Title = title

    # --------------------------------------------------
    # 7. Camera
    # --------------------------------------------------

    view.ResetCamera()

    view.CameraParallelProjection = 1

    # Top-down view for a horizontal cross-section.
    if SLICE_AXIS_USED == "z":

        bounds = slice_filter.GetDataInformation().GetBounds()

        cx = (bounds[0] + bounds[1]) / 2
        cy = (bounds[2] + bounds[3]) / 2

        view.CameraFocalPoint = [cx, cy, 0]
        view.CameraPosition = [cx, cy, 10]
        view.CameraViewUp = [0, 1, 0]

    elif SLICE_AXIS_USED == "y":

        bounds = slice_filter.GetDataInformation().GetBounds()

        cx = (bounds[0] + bounds[1]) / 2
        cz = (bounds[4] + bounds[5]) / 2

        view.CameraFocalPoint = [cx, 0, cz]
        view.CameraPosition = [cx, -10, cz]
        view.CameraViewUp = [0, 0, 1]

    elif SLICE_AXIS_USED == "x":

        bounds = slice_filter.GetDataInformation().GetBounds()

        cy = (bounds[2] + bounds[3]) / 2
        cz = (bounds[4] + bounds[5]) / 2

        view.CameraFocalPoint = [0, cy, cz]
        view.CameraPosition = [-10, cy, cz]
        view.CameraViewUp = [0, 0, 1]

    view.ResetCamera()

    # --------------------------------------------------
    # 8. Render
    # --------------------------------------------------

    log("Rendering CFD results")

    Render()

    # --------------------------------------------------
    # 9. Save screenshot
    # --------------------------------------------------

    output_file = os.path.join(
        OUTPUT_DIR,
        f"aircraft_{FIELD}_{SLICE_AXIS_USED}.png"
    )

    SaveScreenshot(
        output_file,
        view,
        ImageResolution=[
            IMAGE_WIDTH,
            IMAGE_HEIGHT
        ]
    )

    log(f"Screenshot saved: {output_file}")

    log("=== SUCCESS ===")


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        log(f"ERROR: {error}")
        raise
