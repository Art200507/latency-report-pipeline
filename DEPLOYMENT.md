# Hosting and publication controls

Run this long-lived Python app on a container host with persistent storage for SQLite/audio files. Do not deploy background generation as a short-lived Vercel Function.

The public dashboard is read-only by default. `/api/run` requires the server-only `OPERATOR_API_TOKEN` in an Authorization Bearer header. Never put this token in a Vite variable or the public frontend bundle. Use an authenticated operator client to trigger publication. The scheduler is disabled unless `ENABLE_SCHEDULER=true` is deliberately set. Deploying a portfolio demo must not automatically publish podcast episodes.

Provider setup still required: Groq/Gemini credentials, configured audio/storage provider, feed publishing credentials, and persistent storage. Verify a dry run before enabling publication. No publishing jobs were run during this review.
