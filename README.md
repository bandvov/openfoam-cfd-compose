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
`postProcessing/forceCoeffs/`. When the solver finishes, the container log prints a
summary with convergence status and the final Cd, Cl and CmPitch.

## Saved time folders, restart, disk space

`simpleFoam` is a steady solver, so the numbered folders in `results/<CASE_NAME>/`
(`400`, `800`, ...) are snapshots of the full solution at that iteration, written
every `max(100, MAX_ITER/5)` iterations. `0` holds the initial and boundary
conditions. The last folder is the final solution (its number is the iteration where
the run converged, or `MAX_ITER`).

- **Continue a run:** set `RESTART=1` (and `MAX_ITER` to the number of *additional*
  iterations) and run `docker compose up` again. The existing mesh, settings and
  latest solution are reused; nothing is deleted. The log goes to
  `log.simpleFoam.restart-<start time>` and the summary reports the new segment.
  Only `MAX_ITER`, `NPROCS` and `PURGE_WRITE` take effect on a restart. To change
  speed, angle of attack or the mesh, run again with `RESTART=0`; that deletes the
  case and starts from scratch.
- **Save disk space:** `PURGE_WRITE=2` keeps only the last two written snapshots.

## Mesh quality, angle of attack, speed

- `MESH_QUALITY=coarse|medium|fine` (default `medium`). `coarse` is a quick
  sanity check only (about 20 cells across the body, no boundary layer). `medium`
  refines the surface to levels 3-4, adds a refined box around the body and wake,
  and 3 prism layers. `fine` goes to levels 4-5 with 5 layers and needs much more
  RAM and time. `LAYERS`, `WAKE_LEVEL`, `SURFACE_REFINEMENT_MIN/MAX` and
  `MAX_GLOBAL_CELLS` override the preset.
- `ANGLE_OF_ATTACK` (degrees, positive nose-up) pitches the geometry about its
  centre; the flow always runs along +X. Without angle of attack, a symmetric wing
  produces almost no lift.
- `NPROCS=<cores>` runs the solver in parallel (`decomposePar` + `mpirun`).
- `CHORD` and `WING_AREA` default to `auto`: mean chord and top-view planform area
  computed from the STL. Set numbers to use your own reference values.

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
- The STL must have its nose toward -X and "up" as +Z.
- Check mesh independence (run `medium` and `fine` and compare Cd/Cl) before
  trusting any number.

## Example: 30 m/s aircraft

```env
SPEED=30
AIR_DENSITY=1.225
KINEMATIC_VISCOSITY=1.5e-5
ANGLE_OF_ATTACK=4
MESH_QUALITY=medium
NPROCS=4
MAX_ITER=2000
```

## Visualize (optional)

With an NVIDIA GPU and the NVIDIA Container Toolkit:

```bash
cd paraview
docker compose up
```

This renders four images into `results/` from the latest saved time step:
`<case>_U_z.png` (top view), `<case>_U_y.png` and `<case>_p_y.png` (side view through
mid-span, where the airfoil section is visible) and `<case>_psurf.png` (pressure on
the aircraft surface). The views are zoomed on the aircraft; use `ZOOM=full` for the
whole domain and `CASE_NAME=<name>` for another case. `p` is kinematic pressure
(p/rho).

### Streamline picture

`<case>_streamlines.png` is an airliner-style image: 3D streamlines from a seed grid
upstream, drawn as tubes coloured by speed, plus streamlines on the aircraft surface
that follow the wall shear stress (they show the near-wall flow direction and
separation). The solver step now also writes the `wallShearStress` field
(`log.wallShearStress`). For a case you already solved, run once with
`RESTART=1 MAX_ITER=1` to write that field without re-solving, then run the ParaView
compose again. If the field is missing, the image still shows the 3D streamlines.
The picture is only as good as the mesh: a coarse mesh gives rough surface lines.

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
Force directions are +X drag and +Z lift. The far-field sides are symmetry planes,
so very large models relative to the domain, or high angles of attack, can show
blockage effects.
