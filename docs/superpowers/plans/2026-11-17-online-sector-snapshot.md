# Online sector snapshot implementation plan

Goal: publish the user-accepted local sector board online while preserving the original homepage, research radar and news.

Architecture: reuse the accepted Vue board, add an explicit snapshot mode and route, and export sanitized read-only view documents into the deployment output. This first release is a fixed snapshot with its actual collection time. Existing live services and v4 D1 activation gates remain unchanged; no live synchronization is implied.

User authorization: 2026-11-17 request to upload the accepted local board. Earlier instructions authorize autonomous execution without intermediate approvals. Manual publication of this snapshot does not verify supplier redistribution terms or change their recorded status.

- [x] Extract shared board factory, preserve local mode and add deployment snapshot reader, labeling and homepage link.
- [x] Export single-generation latest/catalog/history/details and constituent data; exclude provider envelopes, secrets and local filesystem paths. Generate into ignored build output only.
- [x] Test snapshot catalog filtering and missing-file behavior, existing local views, exporter date alignment, and build. Check browser interaction.
- [x] Deploy with the existing Cloudflare Pages project and production branch. Verify new route/data and original homepage remotely. Record deployment and limitations.

Ruling: fixed snapshot first, because migrating all automatic publishing into D1 would extend this release beyond uploading the accepted version. The UI must say snapshot and never promise 15-minute online refresh.
