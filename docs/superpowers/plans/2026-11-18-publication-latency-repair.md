# Publication latency repair

Problem observed at 15:15Shanghai: public14:21generation, local14:54generation, repeated nine-minute publication timeouts and1102. The full15-date constituent dataset was retransmitted eachcycle; one serialized runner blocked collection while publishing. A separate collector defect set the observation cutoff before quote collection, sometimes excluding every fresh constituent.

Authorized repair (user already approved autonomous operational fixes):

1. Correct quote observation cutoff after unchanged freshness checks; recover real18close.
2. Export daily-v1 documents containing today's detail/member data only, with the existing complete latest/catalog/matrix documents. Publication generation=SHA256('daily-v1\n'+sourceGeneration). Pin currently activated legacy history baseline1a35ffd16bda9c95570c2d484a68a999624ba9027d7cb70f358e2b8a53075015.
3. Merge previous successful daily archives and the legacybaseline on cloud reads. Preserve complete history and per-date member expansion; retain15daily dates plus4recent generations and their pinnedbases. Atomic activation and digests unchanged.
4. Split collection (five-minute wake, fifteen-minute official session gate) from publication (one-minute wake, no providercalls), eachwith its own lock. No accumulated publication can delay a collectionbucket.
5. Batch only small documents using an uncompressed byte cap; large documentpieces stay individual, preserving Workers CPU bounds. Measure actual export/wire/request count and end-to-end activation, not just a one-off success.
6. Test old/new protocol, archive composition/asof/retention, cutoff, sampler/publisher independence. Migrate additive index, deploy, publish full real close, then verify two independent job exits plus publicUI/generation/source timestamp. Record next trading-session evidence honestly as future if unavailable today.
