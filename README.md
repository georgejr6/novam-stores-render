# novam-stores-render

Headless Blender worker that makes branded product images for NOVAM Stores and DIGITVL Stores.
Public repository on purpose: standard GitHub Actions runners are free for public repos. It holds **no keys, no brand data, no client names**.
The only secret is the shared HMAC secret in the repo's Actions secrets (`RENDER_WORKER_SECRET`); the list of store origins is the Actions variable `RENDER_API_BASES`.

## How it works
1. `render.yml` runs every 10 minutes and calls `POST /api/internal/render/claim` on each store origin (signed, see `worker/signing.py`).
2. Each claimed job is a **recipe**: product type, the provider's print area (px + dpi), colours (hex from the provider catalog), logo URL, optional brand-owned inside label, brand colours.
3. Blender (4.2, Cycles on CPU, 40 samples + OpenImageDenoise) builds the product procedurally in inches (`blender/products.py`), places the logo at **true print scale** inside the provider print area (contain-fit, centred: what the provider's default placement does), and renders the shots: `flat`, `angle`, `detail`, `styled` (+ `label` for garments when the brand has its own inside label).
4. Images are converted to WebP and uploaded to the store API (`/upload`), then `/complete` finishes the lease. The store attaches them to the draft product.

Run a sample by hand: Actions -> render -> Run workflow -> `samples: tee,hoodie,mug` (artifacts hold the PNGs). Never render on a laptop.

## Product types
tee, heavy-tee, long-sleeve, hoodie, crewneck, tote, dad-hat, snapback, mug, poster. Models are approximations of an M-size blank built from standard measurements; print areas are the provider's. A type is only *sellable* after the owner has checked a physical sample.

## Models (people)
No model photos are included. `worker/onmodel.py` only uses photos listed in an owner-approved `models/approved.json` whose group is `black` or `latino`; without that file the on-model shot is skipped and stores show garment-only images.

## Inside labels
The label appears only when the brand supplies its own (`labelUrl` in the recipe). There is never a default tag.
