# Think for Value news Reel publisher

This repository contains the public rendering worker for the private Think for Value newsroom. It uses GitHub-hosted macOS runners, local VoxCPM2 inference, and the newsroom's authenticated publishing API. No AI or TTS API key is needed.

The public source contains no newsroom records, generated media, model weights, or credentials. Configure these repository Actions secrets before running the workflow:

- `NEWSROOM_URL`
- `AUTO_PUBLISH_SECRET`
- `SIWC_BYPASS_TOKEN`

The Facebook Page token remains encrypted in the private newsroom database. The worker receives only the two Site API credentials. Do not add secrets to files, workflow logs, issues, or pull requests.

Each run renders into an operating-system temporary directory. The private publish API streams the MP4 directly to Facebook and does not retain a second copy in R2. Temporary audio and video are removed when the run finishes; the GitHub runner is then discarded. Model weights and the compiled TTS binary are cached separately so later runs can reuse them.

The repository is public so standard GitHub-hosted runners can be used without Actions minute charges. Keep all workflow triggers restricted to the default branch and do not add pull-request execution that can access secrets.

