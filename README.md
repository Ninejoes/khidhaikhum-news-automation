# Think for Value news Reel publisher

This repository contains the public rendering worker for the private Think for Value newsroom. It uses GitHub-hosted Ubuntu runners, Gemini 3.8 Flash TTS for Thai narration, and the newsroom's authenticated publishing API.

The public source contains no newsroom records, generated media, model weights, or credentials. Configure these repository Actions secrets before running the workflow:

- `NEWSROOM_URL`
- `AUTO_PUBLISH_SECRET`
- `SIWC_BYPASS_TOKEN`
- `GEMINI_API_KEY`

Scheduled runs post eligible Reels every two hours from 08:25 through 22:25 Bangkok time, after the newsroom collection cycle. Manual runs default to render-only; publishing requires explicitly setting the `publish` input.

The Facebook Page token remains encrypted in the private newsroom database. The worker receives only the Site API credentials and Gemini API key as Actions secrets. Do not add secrets to files, workflow logs, issues, or pull requests.

Gemini free-tier requests may be used by Google to improve its products. Only the narration script is sent to Gemini; use a project/key that remains on the free tier if you require zero API charges.

Each run renders into an operating-system temporary directory. The private publish API streams the MP4 directly to Facebook and does not retain a second copy in R2. Temporary audio and video are removed when the run finishes; the GitHub runner is then discarded.

The repository is public so standard GitHub-hosted runners can be used without Actions minute charges. Keep all workflow triggers restricted to the default branch and do not add pull-request execution that can access secrets.

