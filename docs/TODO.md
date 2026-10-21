# Open items

Known bugs and agreed work that is not started. Each entry says what is wrong, what was already
established about it, and where to start - so picking one up does not mean re-doing the diagnosis.

## "Your bases here" lists other players' bases (reported 2026-10-21)

**What is wrong:** the system card's *Your bases here* and the bases shown on the maps come from
`PlayerStateData.PersistentPlayerBases`, which is **not** a list of the player's own bases. It also
holds every base the player has downloaded or visited, each owned by someone else.

**Measured on the real save (2026-10-21):** 171 entries, of which only **37 are the player's**
(34 `HomePlanetBase` plus one each of `PlayerShipBase`, `FreighterBase`, `PlayerSpaceStationBase`).
The other **134 are `ExternalPlanetBase`** owned by other players - "Calypso Center Portal" by
Ghost-7-Echo, "Das ende" by Xaudi4liveX and so on, mostly clustered at the galaxy centre. **Many of
them appear twice**, so a naive count is wrong as well as a wrong set.

**The fix:** filter by owner, not by type. Every base carries `Owner` with a `UID` (and usually a
`USN`); keep only those whose `UID` is the player's own. Type alone is a weaker test - it happens to
correlate here, but the owner field is the thing that actually says whose base it is, and
`PlayerShipBase` has a `UID` with no `USN`, so test the `UID`.

**Where the player's own UID comes from:** `PlayerStateData` does not carry it. The discovery records
do - `DiscoveryManagerData['DiscoveryData-v1'].Store.Record[*].OWS.UID` is the player's own on his
own discoveries, and the save folder is named `st_<id>` on Steam. Pick one, state which, and do not
guess it from "the most common owner", which would break on a save with few bases.

**Where to change it:** `nms_connector/summary.py` builds the `bases` list (one dict per base) that
everything else reads - `planets_view.Context.bases` / `bases_in()`, `page.py`'s *Bases in this
system* and the bases table, `companion.py`'s base lines, and the map's base points. Filtering at the
source in `summary.py` fixes all of them at once. Decide deliberately whether other players' bases
should be dropped entirely or kept under their own label (they are genuinely useful as portal-hub
markers near a galaxy centre) - but they must never be called *yours*.

**Tests to add:** a save fixture with a mix of owners asserting that only the player's own bases are
returned, that the duplicate `ExternalPlanetBase` entries cannot inflate a count, and that a base
with no `Owner` is not silently treated as the player's.
