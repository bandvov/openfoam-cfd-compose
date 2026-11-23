# OpenFOAM CFD with Python + Docker Compose

A small, reproducible external-flow CFD starter. Python creates the OpenFOAM case,
meshes an STL with `blockMesh` + `snappyHexMesh`, checks the mesh, and runs
steady incompressible RANS with `simpleFoam` and `kOmegaSST`.

## Run

1. Put a triangulated, closed (watertight) STL in `geometry/` and point `GEOMETRY` at it.
   Bundled samples: `model2.stl` (millimetres, 2000 x 1000 x 301 mm; the default,
   with `MODEL_UNITS=mm`) and `model3.stl` (metres, 1 x 1 x 0.3 m; use
   `MODEL_UNITS=m`). Both are half-wings that end on the y=0 plane; they are
   simulated as full bodies, not as symmetry halves.
   `model.stl` is not watertight and contains two separate bodies.
2. Copy `.env.example` to `.env` and adjust the operating point/reference dimensions.
   Docker Compose reads `.env` and passes each variable listed in
   `docker-compose.yml` into the container.
3. Start:

   ```bash
   docker compose up --build
   ```

If no STL exists, the script creates a simple rectangular-wing test body. This is
only a pipeline smoke test, not a realistic aircraft model.

Results are written to `results/<CASE_NAME>/`. Open `results/<CASE_NAME>/case.foam`
in ParaView to inspect fields. Force coefficient history is under
`postProcessing/forceCoeffs/`.

## Important assumptions

- Set `MODEL_UNITS` to the STL's units (`m`, `mm`, `cm`, `in`, `ft`; default `mm`).
  `MESH_SCALE` is an optional explicit factor to metres that overrides it.
- X is the flow direction, Y is spanwise, Z is vertical.
- The STL is approximately aligned with those axes.
- `CHORD` (m) and `WING_AREA` (m^2) are reference dimensions used for coefficient
  normalization; they do not change the geometry and are not affected by `MODEL_UNITS`.
- `SPEED` is the free-stream speed in m/s.
- `KINEMATIC_VISCOSITY` is nu in m^2/s (air near sea level: approximately 1.5e-5).
- The initial setup is incompressible. Keep Mach number below about 0.3.
- The default background mesh and surface refinement are deliberately modest.
  Increase refinement and add boundary layers before trusting engineering results.

## Example: 30 m/s aircraft

```env
SPEED=30
AIR_DENSITY=1.225
KINEMATIC_VISCOSITY=1.5e-5
CHORD=1.2
WING_AREA=1.8
MAX_ITER=1500
```

## Visualize (optional)

With an NVIDIA GPU and the NVIDIA Container Toolkit:

```bash
cd paraview
docker compose up
```

This renders `results/aircraft_<FIELD>_<SLICE_AXIS>.png` from the latest saved
time step. Use `CASE_NAME=<name> FIELD=p SLICE_AXIS=y docker compose up` to change
the case, field (`U` or `p`) or slice plane. `p` is kinematic pressure (p/rho).

## Troubleshooting

- `Could not find OpenFOAM's etc/bashrc`: set `OPENFOAM_BASHRC` to its path in the image.
- Image pull fails: choose an existing tag with
  `docker compose build --build-arg OPENFOAM_IMAGE_TAG=<tag>` or set
  `OPENFOAM_IMAGE_TAG` in `.env`.

## Re-run

The case directory is recreated each run. Copy any result you want to keep
before starting another run. Change `CASE_NAME` to keep separate named runs.

## Limitations / next steps

This starter is not a validated aircraft-design workflow. Mesh independence,
y+ and boundary-layer resolution, turbulence-model sensitivity, domain-size
sensitivity, and convergence of force coefficients must be checked. For
transonic/compressible flow use a compressible solver and appropriate physics.
The current force directions assume +X drag and +Z lift.
