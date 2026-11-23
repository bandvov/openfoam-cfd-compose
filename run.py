#!/usr/bin/env python3
"""
Generate and run a basic external-aerodynamics OpenFOAM case.

Coordinate convention:
  X = freestream / aircraft longitudinal axis
  Y = spanwise
  Z = up

Input geometry must be STL in metres, approximately aligned with +X flow.
The script recentres it around its bounding-box centre.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import trimesh

ROOT = Path("/workspace")
RESULTS = ROOT / "results"
CASE_NAME = os.getenv("CASE_NAME", "aircraft")
CASE = RESULTS / CASE_NAME
GEOMETRY = Path(os.getenv("GEOMETRY", str(ROOT / "geometry/model2.stl")))

U_INF = float(os.getenv("SPEED", "30"))
RHO = float(os.getenv("AIR_DENSITY", "1.225"))
NU = float(os.getenv("KINEMATIC_VISCOSITY", "1.5e-5"))
CHORD = float(os.getenv("CHORD", "1.0"))
AREA = float(os.getenv("WING_AREA", "1.0"))
TI = float(os.getenv("TURBULENCE_INTENSITY", "0.01"))
MAX_ITER = int(os.getenv("MAX_ITER", "3000"))
# Units of the STL file. MODEL_UNITS picks the factor that converts them to
# metres; MESH_SCALE (if set) overrides it with an explicit factor.
UNIT_TO_METRES = {
    "m": 1.0, "meter": 1.0, "metre": 1.0, "meters": 1.0, "metres": 1.0,
    "mm": 1e-3, "millimeter": 1e-3, "millimetre": 1e-3,
    "millimeters": 1e-3, "millimetres": 1e-3,
    "cm": 1e-2, "centimeter": 1e-2, "centimetre": 1e-2,
    "in": 0.0254, "inch": 0.0254, "inches": 0.0254,
    "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
}
MODEL_UNITS = os.getenv("MODEL_UNITS", "mm").strip().lower() or "m"
if MODEL_UNITS not in UNIT_TO_METRES:
    raise SystemExit(
        f"ERROR: unknown MODEL_UNITS '{MODEL_UNITS}'. "
        f"Use one of: m, mm, cm, in, ft (or set MESH_SCALE explicitly)."
    )
_scale_override = os.getenv("MESH_SCALE", "").strip()
MESH_SCALE = (float(_scale_override) if _scale_override
              else UNIT_TO_METRES[MODEL_UNITS])

# Background mesh controls. These defaults keep the first test mesh modest.
BACKGROUND_CELLS_PER_LENGTH = float(
    os.getenv("BACKGROUND_CELLS_PER_LENGTH", "16")
)
MAX_BACKGROUND_NX = int(os.getenv("MAX_BACKGROUND_NX", "100"))
MAX_BACKGROUND_NY = int(os.getenv("MAX_BACKGROUND_NY", "70"))
MAX_BACKGROUND_NZ = int(os.getenv("MAX_BACKGROUND_NZ", "60"))
MAX_GLOBAL_CELLS = int(os.getenv("MAX_GLOBAL_CELLS", "2000000"))
MAX_LOCAL_CELLS = int(os.getenv("MAX_LOCAL_CELLS", "1000000"))
SURFACE_REFINEMENT_MIN = int(os.getenv("SURFACE_REFINEMENT_MIN", "1"))
SURFACE_REFINEMENT_MAX = int(os.getenv("SURFACE_REFINEMENT_MAX", "2"))



def find_openfoam_bashrc() -> str:
    """Locate OpenFOAM's etc/bashrc. Override with OPENFOAM_BASHRC if needed."""
    explicit = os.getenv("OPENFOAM_BASHRC")
    if explicit:
        if not Path(explicit).is_file():
            raise FileNotFoundError(f"OPENFOAM_BASHRC does not exist: {explicit}")
        return explicit

    candidates: list[Path] = []
    project_dir = os.getenv("WM_PROJECT_DIR")
    if project_dir:
        candidates.append(Path(project_dir) / "etc" / "bashrc")
    candidates += [
        Path("/opt/OpenFOAM-v2506/etc/bashrc"),
        Path("/usr/lib/openfoam/openfoam2506/etc/bashrc"),
    ]
    for pattern in ("/opt/OpenFOAM-v*/etc/bashrc",
                    "/opt/openfoam*/etc/bashrc",
                    "/usr/lib/openfoam/openfoam*/etc/bashrc"):
        candidates += sorted(Path("/").glob(pattern.lstrip("/")))

    for path in candidates:
        if path.is_file():
            return str(path)
    raise FileNotFoundError(
        "Could not find OpenFOAM's etc/bashrc. Set OPENFOAM_BASHRC to its path "
        "(inside the container: find / -name bashrc -path '*openfoam*')."
    )



def run(command: str, log_name: str | None = None) -> None:
    """Run an OpenFOAM command and stream its output to Docker logs."""
    print(f"\n>>> {command}", flush=True)

    # Fail if OpenFOAM's environment cannot be loaded. Silently ignoring a
    # failed bashrc can lead to confusing 'command not found' errors later.
    full_cmd = (
        f"source '{find_openfoam_bashrc()}' && "
        f"cd '{CASE}' && "
        f"{command}"
    )

    if log_name:
        log_path = CASE / log_name
        with log_path.open("w", buffering=1) as log:
            process = subprocess.Popen(
                ["bash", "-lc", full_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)

            returncode = process.wait()
            if returncode != 0:
                raise subprocess.CalledProcessError(returncode, command)
    else:
        subprocess.run(
            ["bash", "-lc", full_cmd],
            check=True,
        )


def write(path: str, content: str) -> None:
    target = CASE / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.strip() + "\n")


def foam_header(class_name: str, object_name: str) -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       {class_name};
    object      {object_name};
}}"""


def prepare_geometry():
    GEOMETRY.parent.mkdir(parents=True, exist_ok=True)
    if GEOMETRY.exists():
        mesh = trimesh.load(GEOMETRY, force="mesh")
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
            raise RuntimeError(
                f"Could not read a triangle mesh from {GEOMETRY}")
        print(f"Loaded geometry: {GEOMETRY} ({len(mesh.faces)} triangles)")
        mesh.apply_scale(MESH_SCALE)
        print(f"Model units: {MODEL_UNITS} (scale to metres: {MESH_SCALE:g})")
        if not mesh.is_watertight:
            print("WARNING: STL is not watertight; snappyHexMesh may leak or "
                  "produce a poor mesh. Repair the surface if meshing fails.",
                  flush=True)
        try:
            # Needs scipy or networkx; skip this advisory check if missing.
            n_bodies = len(mesh.split(only_watertight=False))
            if n_bodies > 1:
                print(f"WARNING: STL contains {n_bodies} disconnected bodies.",
                      flush=True)
        except Exception as exc:  # noqa: BLE001 - purely informational
            print(f"Note: skipped disconnected-body check ({exc}).", flush=True)
        lo, hi = mesh.bounds
        if abs(hi[1]) < 1e-6 * max(mesh.extents) or abs(lo[1]) < 1e-6 * max(mesh.extents):
            print("WARNING: geometry ends on the y=0 plane (looks like a half "
                  "model). It is recentred and simulated as a full body in a "
                  "box; it is NOT treated as a symmetry-plane half model.",
                  flush=True)
    else:
        print(
            f"No STL found at {GEOMETRY}; creating a simple rectangular-wing test geometry.")
        # A basic finite-thickness wing-like box. Replace with your own STL for real work.
        mesh = trimesh.creation.box(
            extents=[CHORD, max(3.0 * CHORD, 1.0), 0.06 * CHORD])

    bounds = mesh.bounds.copy()
    centre = bounds.mean(axis=0)
    mesh.apply_translation(-centre)
    bounds = mesh.bounds.copy()

    # Use a stable name for snappyHexMesh's surface patch.
    tri_dir = CASE / "constant" / "triSurface"
    tri_dir.mkdir(parents=True, exist_ok=True)
    mesh.export(tri_dir / "aircraft.stl")

    ext = bounds[1] - bounds[0]
    if min(ext) <= 0:
        raise RuntimeError(
            "Geometry has zero extent in at least one direction.")
    characteristic = max(float(ext[0]), float(ext[1]), float(ext[2]))
    return bounds, ext, characteristic


def write_case(bounds, ext, length):
    xmin, ymin, zmin = bounds[0]
    xmax, ymax, zmax = bounds[1]

    # A generous far-field box: 5 characteristic lengths upstream and
    # 15 downstream. Side/top/bottom boundaries are symmetry planes.
    x0, x1 = xmin - 5.0 * length, xmax + 15.0 * length
    yhalf = max(5.0 * length, 2.5 * float(ext[1]))
    zhalf = max(5.0 * length, 2.5 * float(ext[2]))
    y0, y1 = -yhalf, yhalf
    z0, z1 = -zhalf, zhalf

    # Coarse background grid; snappyHexMesh refines around the STL.
    # A target spacing of characteristic_length / 16 and conservative caps
    # keep the initial mesh around a few hundred thousand cells for a typical
    # aircraft case, rather than starting with millions of cells.
    if BACKGROUND_CELLS_PER_LENGTH <= 0:
        raise ValueError("BACKGROUND_CELLS_PER_LENGTH must be positive.")

    target = length / BACKGROUND_CELLS_PER_LENGTH
    nx = max(24, min(MAX_BACKGROUND_NX, math.ceil((x1 - x0) / target)))
    ny = max(20, min(MAX_BACKGROUND_NY, math.ceil((y1 - y0) / target)))
    nz = max(20, min(MAX_BACKGROUND_NZ, math.ceil((z1 - z0) / target)))

    print(
        "Background mesh dimensions: "
        f"{nx} x {ny} x {nz} = {nx * ny * nz:,} cells",
        flush=True,
    )

    write("system/blockMeshDict", f"""
{foam_header("dictionary", "blockMeshDict")}
convertToMeters 1;
vertices
(
    ({x0} {y0} {z0})
    ({x1} {y0} {z0})
    ({x1} {y1} {z0})
    ({x0} {y1} {z0})
    ({x0} {y0} {z1})
    ({x1} {y0} {z1})
    ({x1} {y1} {z1})
    ({x0} {y1} {z1})
);
blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)
);
edges ();
boundary
(
    inlet
    {{
        type patch;
        faces ((0 4 7 3));
    }}
    outlet
    {{
        type patch;
        faces ((1 2 6 5));
    }}
    farfield
    {{
        type symmetry;
        faces
        (
            (0 1 5 4)
            (3 7 6 2)
            (0 3 2 1)
            (4 5 6 7)
        );
    }}
);
mergePatchPairs ();
""")

    write("system/surfaceFeatureExtractDict", f"""
{foam_header("dictionary", "surfaceFeatureExtractDict")}
aircraft.stl
{{
    extractionMethod    extractFromSurface;
    extractFromSurfaceCoeffs
    {{
        includedAngle   150;
    }}
    writeObj            no;
}}
""")

    write("system/snappyHexMeshDict", f"""
{foam_header("dictionary", "snappyHexMeshDict")}
castellatedMesh true;
snap            true;
addLayers       false;

geometry
{{
    aircraft.stl
    {{
        type triSurfaceMesh;
        name aircraft;
    }}
}};

castellatedMeshControls
{{
    maxLocalCells {MAX_LOCAL_CELLS};
    maxGlobalCells {MAX_GLOBAL_CELLS};
    minRefinementCells 10;
    maxLoadUnbalance 0.10;
    nCellsBetweenLevels 3;

    features ();

    refinementSurfaces
    {{
        aircraft
        {{
            level ({SURFACE_REFINEMENT_MIN} {SURFACE_REFINEMENT_MAX});
            patchInfo
            {{
                type wall;
            }}
        }}
    }}

    resolveFeatureAngle 30;
    refinementRegions {{}};

    // Guaranteed outside the body and inside the upstream part of the domain.
    locationInMesh ({xmin - 2.0 * length} 0 0);
    allowFreeStandingZoneFaces true;
}}

snapControls
{{
    nSmoothPatch 3;
    tolerance 2.0;
    nSolveIter 30;
    nRelaxIter 5;
    nFeatureSnapIter 10;
    implicitFeatureSnap false;
    explicitFeatureSnap false;
    multiRegionFeatureSnap false;
}}

addLayersControls
{{
    relativeSizes true;
    layers {{}};
    expansionRatio 1.0;
    finalLayerThickness 0.3;
    minThickness 0.1;
    nGrow 0;
    featureAngle 60;
    slipFeatureAngle 30;
    nRelaxIter 3;
    nSmoothSurfaceNormals 1;
    nSmoothNormals 3;
    nSmoothThickness 10;
    maxFaceThicknessRatio 0.5;
    maxThicknessToMedialRatio 0.3;
    minMedianAxisAngle 90;
    nBufferCellsNoExtrude 0;
    nLayerIter 50;
}}

meshQualityControls
{{
    #include "meshQualityDict"
}}
mergeTolerance 1e-6;
""")

    write("system/meshQualityDict", f"""
{foam_header("dictionary", "meshQualityDict")}
maxNonOrtho 65;
maxBoundarySkewness 20;
maxInternalSkewness 4;
maxConcave 80;
minVol 1e-13;
minTetQuality 1e-15;
minArea -1;
minTwist 0.02;
minDeterminant 0.001;
minFaceWeight 0.02;
minVolRatio 0.01;
minTriangleTwist -1;
nSmoothScale 4;
errorReduction 0.75;
""")

    write("system/controlDict", f"""
{foam_header("dictionary", "controlDict")}
application simpleFoam;
startFrom startTime;
startTime 0;
stopAt endTime;
endTime {MAX_ITER};
deltaT 1;
writeControl timeStep;
writeInterval {max(100, MAX_ITER // 5)};
purgeWrite 0;
writeFormat ascii;
writePrecision 8;
writeCompression off;
timeFormat general;
timePrecision 6;
runTimeModifiable true;

functions
{{
    forceCoeffs
    {{
        type            forceCoeffs;
        libs            ("libforces.so");
        patches         (aircraft);
        rho             rhoInf;
        rhoInf          {RHO};
        liftDir         (0 0 1);
        dragDir         (1 0 0);
        pitchAxis       (0 1 0);
        CofR            (0 0 0);
        magUInf          {U_INF};
        lRef             {CHORD};
        Aref             {AREA};
        writeControl     timeStep;
        writeInterval    10;
    }}
}}
""")

    write("system/fvSchemes", f"""
{foam_header("dictionary", "fvSchemes")}
ddtSchemes {{ default steadyState; }}
gradSchemes {{ default cellLimited Gauss linear 1; }}
divSchemes
{{
    default none;
    div(phi,U) bounded Gauss linearUpwind grad(U);
    div(phi,k) bounded Gauss upwind;
    div(phi,omega) bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}}
laplacianSchemes {{ default Gauss linear corrected; }}
interpolationSchemes {{ default linear; }}
snGradSchemes {{ default corrected; }}
wallDist {{ method meshWave; }}
""")

    write("system/fvSolution", f"""
{foam_header("dictionary", "fvSolution")}

solvers
{{
    p
    {{
        solver PCG;
        preconditioner DIC;
        tolerance 1e-7;
        relTol 0.01;
    }}

    "(U|k|omega)"
    {{
        solver smoothSolver;
        smoother symGaussSeidel;
        tolerance 1e-7;
        relTol 0.05;
    }}
}}

SIMPLE
{{
    nNonOrthogonalCorrectors 1;
    consistent yes;

    residualControl
    {{
        p 1e-4;
        U 1e-5;
        "(k|omega)" 1e-5;
    }}
}}

relaxationFactors
{{
    fields
    {{
        p 0.2;
    }}

    equations
    {{
        U 0.5;
        k 0.5;
        omega 0.5;
    }}
}}
""")

    k = 1.5 * (U_INF * TI) ** 2
    omega = math.sqrt(k) / (0.09 ** 0.25 * max(0.07 * CHORD, 1e-4))

    write("constant/turbulenceProperties", f"""
{foam_header("dictionary", "turbulenceProperties")}
simulationType RAS;
RAS
{{
    RASModel kOmegaSST;
    turbulence on;
    printCoeffs on;
}}
""")
    
    write("constant/transportProperties", f"""
{foam_header("dictionary", "transportProperties")}
transportModel  Newtonian;
nu              [0 2 -1 0 0 0 0] {NU};
""")

    write("0/U", f"""
{foam_header("volVectorField", "U")}
dimensions [0 1 -1 0 0 0 0];
internalField uniform ({U_INF} 0 0);
boundaryField
{{
    inlet {{ type fixedValue; value uniform ({U_INF} 0 0); }}
    outlet {{ type zeroGradient; }}
    farfield {{ type symmetry; }}
    aircraft {{ type noSlip; }}
}}
""")

    write("0/p", f"""
{foam_header("volScalarField", "p")}
dimensions [0 2 -2 0 0 0 0];
internalField uniform 0;
boundaryField
{{
    inlet {{ type zeroGradient; }}
    outlet {{ type fixedValue; value uniform 0; }}
    farfield {{ type symmetry; }}
    aircraft {{ type zeroGradient; }}
}}
""")

    write("0/k", f"""
{foam_header("volScalarField", "k")}
dimensions [0 2 -2 0 0 0 0];
internalField uniform {k};
boundaryField
{{
    inlet {{ type fixedValue; value uniform {k}; }}
    outlet {{ type zeroGradient; }}
    farfield {{ type symmetry; }}
    aircraft {{ type kqRWallFunction; value uniform {k}; }}
}}
""")

    write("0/omega", f"""
{foam_header("volScalarField", "omega")}
dimensions [0 0 -1 0 0 0 0];
internalField uniform {omega};
boundaryField
{{
    inlet {{ type fixedValue; value uniform {omega}; }}
    outlet {{ type zeroGradient; }}
    farfield {{ type symmetry; }}
    aircraft {{ type omegaWallFunction; value uniform {omega}; }}
}}
""")

    write("0/nut", f"""
{foam_header("volScalarField", "nut")}
dimensions [0 2 -1 0 0 0 0];
internalField uniform 0;
boundaryField
{{
    inlet {{ type calculated; value uniform 0; }}
    outlet {{ type calculated; value uniform 0; }}
    farfield {{ type symmetry; }}
    aircraft {{ type nutkWallFunction; value uniform 0; }}
}}
""")


def main():
    if U_INF <= 0 or RHO <= 0 or NU <= 0 or CHORD <= 0 or AREA <= 0:
        raise ValueError(
            "SPEED, AIR_DENSITY, KINEMATIC_VISCOSITY, CHORD and WING_AREA must be positive.")
    if not 0 < TI < 1:
        raise ValueError(
            "TURBULENCE_INTENSITY must be a fraction between 0 and 1.")
    if MAX_ITER <= 0:
        raise ValueError("MAX_ITER must be positive.")
    if MESH_SCALE <= 0:
        raise ValueError("MESH_SCALE must be positive.")
    if U_INF > 100:
        print("WARNING: SPEED > 100 m/s is outside the incompressible "
              "(Mach < ~0.3) assumption of simpleFoam.", flush=True)
    if MAX_GLOBAL_CELLS <= 0 or MAX_LOCAL_CELLS <= 0:
        raise ValueError("Mesh cell limits must be positive.")
    if SURFACE_REFINEMENT_MIN < 0 or SURFACE_REFINEMENT_MAX < SURFACE_REFINEMENT_MIN:
        raise ValueError("Invalid surface refinement levels.")

    if CASE.exists():
        print(f"Removing previous case directory: {CASE}", flush=True)
        shutil.rmtree(CASE)
    CASE.mkdir(parents=True)

    bounds, ext, length = prepare_geometry()
    write_case(bounds, ext, length)

    print("\n=== Configuration ===", flush=True)
    print(f"Characteristic length: {length:.6g} m", flush=True)
    print(f"Background cells per length: {BACKGROUND_CELLS_PER_LENGTH}", flush=True)
    print(
        f"Surface refinement: {SURFACE_REFINEMENT_MIN} "
        f"to {SURFACE_REFINEMENT_MAX}",
        flush=True,
    )
    print(f"Maximum global cells: {MAX_GLOBAL_CELLS:,}", flush=True)
    print(f"Maximum simpleFoam iterations: {MAX_ITER:,}", flush=True)

    print("\n=== OpenFOAM pipeline ===", flush=True)
    (CASE / "case.foam").touch()
    run("blockMesh", "log.blockMesh")
    run("surfaceFeatureExtract", "log.surfaceFeatureExtract")
    run("snappyHexMesh -overwrite", "log.snappyHexMesh")
    run("checkMesh", "log.checkMesh")
    run("simpleFoam", "log.simpleFoam")

    print("\nSimulation finished.")
    print(f"Case and fields: {CASE}")
    print(f"Force coefficients: {CASE / 'postProcessing' / 'forceCoeffs'}")
    print(f"Open results/{CASE_NAME}/case.foam in ParaView to inspect pressure and velocity fields.")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print(
            f"\nERROR: command failed with exit code {exc.returncode}", file=sys.stderr)
        print("Inspect the corresponding log.* file under results/<case-name>/", file=sys.stderr)
        sys.exit(exc.returncode)
