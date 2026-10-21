# Open items

Known bugs and agreed work that is not started. Each entry says what is wrong, what was already
established about it, and where to start - so picking one up does not mean re-doing the diagnosis.

## Done

### "Your bases here" listed other players' bases - fixed 2026-10-21 (0.15.0-beta.12)

`PersistentPlayerBases` holds downloaded and visited bases too (134 of 171 on the real save, 67 of them
stored twice). `summary.summarize` now marks each base `mine` by comparing `Owner.UID` with the player's own
id from `CommonStateData.UsedDiscoveryOwnersV2`, falling back to the base type only when the save does not
say who the player is; re-downloaded copies are merged by `RID`, newest kept. Every view filters on `mine`
and shows the rest separately. Tests: `tests/test_base_owners.py`.
