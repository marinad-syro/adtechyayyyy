# BrainText — Learning Notes

## TribeV2 (Meta AI)
**What it is:** A deep learning model that predicts fMRI brain responses to naturalistic stimuli — text, audio, or video.  
**Why we're using it:** It lets us map any text to predicted neural activation patterns on the cortical surface.  
**How it works here:** Text → gTTS converts it to audio → Whisper transcribes it to word-level events → a Transformer model maps those events to ~20,000 predicted activation values on the "fsaverage5" cortical mesh (a standard anatomical template brain). We then group those values by named brain regions.

## HCP-MMP1 Parcellation
**What it is:** The Human Connectome Project Multi-Modal Parcellation — a standard atlas that divides the cortex into 180 named areas per hemisphere.  
**Why we're using it:** TribeV2's output lives on the fsaverage5 mesh; we need to map the 20k vertices back to human-readable region names like "Broca's Area" or "V1".  
**How it works here:** `get_hcp_roi_indices(["44", "45"], hemi="both", mesh="fsaverage5")` returns the vertex indices that belong to those HCP regions, so we can average predictions within each named region.

## FastAPI
**What it is:** A Python web framework for building APIs, with automatic async support and OpenAPI docs.  
**Why we're using it:** Serves both the REST API (`/api/predict`) and the static frontend from a single process. The `run_in_executor` call offloads the heavy TribeV2 inference to a thread so the event loop doesn't block.

## SVG `clipPath`
**What it is:** An SVG feature that clips (masks) any element to the shape of a defined path.  
**Why we're using it:** The brain regions are defined as simple rectangles/polygons, but the `brain-clip` clipPath trims them into the organic brain silhouette shape automatically — no complex path math needed per region.

## Activation Color Scale
The UI maps the 0–1 normalized activation to: dark navy → deep indigo → violet → orange → gold.  
This mimics fMRI "hot" colormaps (cold = low activity, warm/bright = high activity), which neuroscientists already recognize intuitively.

## fsaverage5
**What it is:** A standard low-resolution brain surface mesh with 10,242 vertices per hemisphere (~20k total). Widely used because it's small enough to work with on a laptop while preserving anatomical topology.  
**Why it matters:** TribeV2 predictions are in this space. When the model says vertex #4521 has activation 0.82, that vertex corresponds to a specific point on the average human brain surface.
