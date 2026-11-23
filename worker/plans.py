"""Per product type: where the logo goes on the provider's print area and which of the provider's own product photos we use.

The product photos are Printful Mockup Generator styles, picked by their (category, view) NAME, not by numeric id, so the
same plan survives the provider re-numbering styles. Every style listed here was looked at by eye (2026-11-23).

Rules baked in:
  * People: only styles reviewed as showing Black or Latino models are listed under "model" (never a white model). A type with
    no reviewed model style simply has no "model" shot. Everything else is garment/product only.
  * No inside labels / tags in these photos (labels are applied at fulfilment, and only when a brand has its own).
  * The server (src/modules/renders/types.ts, RENDER_TYPES) lists the same shots per type. tests/test_plans.py pins the contract.

Logo placement: the logo is fitted ("contain") into `box` (inches) of the print area `area` (inches), centred left to right;
`top` is the offset from the top of the print area (None = centred vertically). Printful requires the layer aspect ratio to match
the file within 2%, so the height is always derived from the real image.
"""

# shot name -> (category_name, view_name) in Printful's mockup style list
PLANS = {
    "tee": {
        "productId": 71,
        "placement": "front",
        "technique": "dtg",
        "area": (12.0, 16.0),
        "box": (9.0, 11.2),
        "top": 2.0,
        "shots": {
            "flat": ("Flat", "Front"),
            "angle": ("On Hanger", "Front"),
            "detail": ("Wrinkled", "Front"),
            "styled": ("Flat Lifestyle", "Front"),
            "model": ("Men's 2", "Front"),  # reviewed: Black model
        },
    },
    "hoodie": {
        "productId": 380,
        "placement": "front",
        "technique": "dtg",
        "area": (12.0, 12.0),
        "box": (6.5, 8.0),
        "top": 1.0,
        "shots": {
            "flat": ("Flat 2", "Front"),
            "angle": ("On Hanger", "Front"),
            "detail": ("Folded, Premium", "Front"),
            "styled": ("Flat, Premium", "Front"),
            "model": ("Women's 2", "Front"),  # reviewed: Black model
        },
    },
    "crewneck": {
        "productId": 411,
        "placement": "front",
        "technique": "dtg",
        "area": (12.0, 16.0),
        "box": (8.0, 10.0),
        "top": 1.5,
        "shots": {
            "flat": ("Flat", "Front"),
            "angle": ("On Hanger", "Front"),
            "styled": ("Ghost", "Front"),
            "model": ("Men's 2", "Front"),  # reviewed: Black model
        },
    },
    "tote": {
        "productId": 367,
        "placement": "front",
        "technique": "dtg",
        "area": (10.0, 10.0),
        "box": (6.5, 8.0),
        "top": 1.0,
        "shots": {
            "flat": ("Flat", "Front"),
            "angle": ("Hanger", "Front"),
            "styled": ("Flat Lifestyle", "Front"),
        },
    },
    "dad-hat": {
        "productId": 206,
        "placement": "embroidery_front_large",
        "technique": "embroidery",
        "area": (5.5, 2.0),
        "box": (5.5, 2.0),
        "top": None,
        "shots": {
            "flat": ("Flat", "Front"),
            "angle": ("Flat", "Right Front"),
            "detail": ("Flat Lifestyle", "Right Front"),
            "styled": ("Flat Lifestyle", "Front"),
        },
    },
    "mug": {
        "productId": 19,
        "placement": "default",
        "technique": "sublimation",
        "area": (9.0, 3.5),  # 11 oz row of the provider's style list
        "box": (2.8, 3.3),
        "top": None,
        "shots": {
            "flat": ("Default", "Front view"),
        },
    },
    "poster": {
        "productId": 1,
        "placement": "default",
        "technique": "digital",
        "area": (18.0, 24.0),  # 18x24 in row
        "box": (13.0, 17.0),
        "top": None,
        "fill_if_aspect": 0.04,  # artwork already shaped like the poster: print it full bleed
        "shots": {
            "flat": ("Flat", "Front"),
            "styled": ("Lifestyle 4", "Front"),
            "angle": ("Lifestyle 6", "Front"),
            "detail": ("Lifestyle 8", "Front"),
        },
    },
}


def fit_layer(plan: dict, logo_w: int, logo_h: int) -> dict:
    """Layer position in inches for a logo of the given pixel size. Aspect ratio is exact (provider tolerance is 2%)."""
    aw, ah = plan["area"]
    ratio = logo_h / logo_w
    fill = plan.get("fill_if_aspect")
    if fill and abs(ratio - ah / aw) / (ah / aw) <= fill:
        return {"width": aw, "height": round(aw * ratio, 4), "top": 0, "left": 0}
    bw, bh = plan["box"]
    w = min(bw, bh / ratio, aw)
    h = w * ratio
    if h > ah:
        w, h = ah / ratio, ah
    top = plan["top"] if plan["top"] is not None else (ah - h) / 2
    top = max(0.0, min(top, ah - h))
    return {"width": round(w, 4), "height": round(w * ratio, 4), "top": round(top, 4), "left": round((aw - w) / 2, 4)}
