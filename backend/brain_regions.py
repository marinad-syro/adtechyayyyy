"""Map TribeV2 fsaverage5 predictions to named cortical regions via HCP-MMP1 atlas."""

import numpy as np
from functools import lru_cache

REGION_DEFINITIONS = {
    "prefrontal": {
        "display_name": "Prefrontal Cortex",
        "description": "Planning, decision-making, executive control",
        "rois": [
            "9-46d", "9-46v", "p9-46v", "a9-46v", "46",
            "SFL", "8AV", "8AD", "8BL", "8BM", "9p", "9a",
            "10v", "10r", "10d", "11l", "13l", "47l",
            "a47r", "p47r", "s47r",
        ],
    },
    "brocas": {
        "display_name": "Broca's Area",
        "description": "Language production, syntactic processing",
        "rois": ["44", "45", "IFJp", "IFJa", "IFSp", "IFSa"],
    },
    "motor": {
        "display_name": "Motor Cortex",
        "description": "Movement planning and execution",
        "rois": ["4", "6r", "6ma", "FEF", "55b", "6mp", "6v", "PEF"],
    },
    "somatosensory": {
        "display_name": "Somatosensory Cortex",
        "description": "Touch, proprioception, body sensation",
        "rois": ["3a", "3b", "1", "2", "43", "OP4", "OP2-3", "52"],
    },
    "parietal": {
        "display_name": "Parietal Cortex",
        "description": "Spatial awareness, attention, multisensory integration",
        "rois": [
            "5m", "5L", "5mv", "7m", "7AL", "7PL",
            "MIP", "AIP", "VIP", "LIPv", "LIPd", "7PC",
            "IP1", "IP2", "PF", "PFm", "PFt", "PGi", "PGp", "PGs", "PFop",
        ],
    },
    "occipital": {
        "display_name": "Visual Cortex",
        "description": "Visual processing, imagery, object recognition",
        "rois": [
            "V1", "V2", "V3", "V4", "V3A", "V3B",
            "V6", "V6A", "V7", "V8", "V3CD",
            "LO1", "LO2", "LO3", "MT", "MST",
            "FFC", "PIT", "VVC", "VMV1", "VMV2", "VMV3",
        ],
    },
    "auditory": {
        "display_name": "Auditory Cortex",
        "description": "Sound and speech perception",
        "rois": ["A1", "LBelt", "MBelt", "PBelt", "A4", "A5", "RI"],
    },
    "wernickes": {
        "display_name": "Wernicke's Area",
        "description": "Language comprehension, semantic processing",
        "rois": [
            "STSdp", "STSda", "STSvp", "STSva",
            "TPOJ1", "TPOJ2", "TPOJ3", "STV",
            "TE1p", "TE1m", "TE2p",
        ],
    },
    "temporal": {
        "display_name": "Temporal Lobe",
        "description": "Memory, face/object recognition, semantic knowledge",
        "rois": [
            "TE1a", "TE2a", "TGv", "TGd", "TF",
            "PeEc", "EC", "PHA1", "PHA2", "PHA3",
        ],
    },
    "acc": {
        "display_name": "Anterior Cingulate Cortex",
        "description": "Emotional salience, attention, conflict detection — lights up for surprising or emotionally resonant content",
        "rois": ["p24", "a24", "24dd", "24dv", "d32", "p32", "25", "33pr"],
    },
    "insula": {
        "display_name": "Insula",
        "description": "Bodily emotional response, gut-feeling, disgust/pleasure — strongly linked to consumer preference and brand perception",
        "rois": ["Ig", "PoI2", "PoI1", "AAIC", "AVI", "MI", "FOP1", "FOP2", "FOP3", "FOP4", "FOP5"],
    },
    "ofc": {
        "display_name": "Orbitofrontal Cortex",
        "description": "Reward valuation, price perception, brand preference — encodes subjective value during decision-making",
        "rois": ["OFC", "47m"],
    },
    "pcc": {
        "display_name": "Posterior Cingulate Cortex",
        "description": "Self-referential thinking, autobiographical memory — active when people imagine themselves using a product",
        "rois": ["23c", "23d", "d23ab", "v23ab", "RSC", "ProS", "DVT", "POS2", "31a", "31pd", "31pv"],
    },
}


@lru_cache(maxsize=1)
def _get_region_vertex_indices() -> dict:
    from tribev2.utils import get_hcp_roi_indices

    region_indices = {}
    for region_id, region_def in REGION_DEFINITIONS.items():
        valid = []
        for roi in region_def["rois"]:
            try:
                idx = get_hcp_roi_indices([roi], hemi="both", mesh="fsaverage5")
                valid.append(idx)
            except ValueError:
                pass
        if valid:
            region_indices[region_id] = np.concatenate(valid)
        else:
            print(f"Warning: no valid HCP ROIs found for '{region_id}'")
    return region_indices


def get_region_activations(avg_pred: np.ndarray) -> dict:
    """Average per-vertex TribeV2 predictions into named regions, normalize 0-1."""
    region_indices = _get_region_vertex_indices()

    raw = {}
    for region_id, indices in region_indices.items():
        if len(indices):
            raw[region_id] = float(avg_pred[indices].mean())

    values = list(raw.values())
    lo, hi = min(values), max(values)
    span = hi - lo

    normalized = {k: (v - lo) / span if span > 1e-8 else 0.5 for k, v in raw.items()}

    sorted_regions = sorted(normalized.items(), key=lambda x: x[1], reverse=True)
    return {
        "activations": normalized,
        "top_regions": [
            {
                "id": rid,
                "name": REGION_DEFINITIONS[rid]["display_name"],
                "description": REGION_DEFINITIONS[rid]["description"],
                "activation": act,
            }
            for rid, act in sorted_regions
        ],
    }
