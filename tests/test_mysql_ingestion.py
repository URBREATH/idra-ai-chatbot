import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.mysql import repositories as repo
from app.ingestion.payload_builder import extract_attrs
from app.ingestion.service import build_distribution_info, content_hash, get_entity_type


def _rows():
    return {
        "catalogues": [{"id": 96, "name": "Paris Open Data", "publisher_name": "City of Paris", "country": "FR"}],
        "datasets": [
            {"dataset_id": "arbres-96", "nodeID": "96", "title": "Les arbres",
             "description": "<p>Liste des <b>arbres</b> &amp; jardins</p><p>Deuxième</p>",
             "landingPage": "http://opendata.paris.fr/arbres", "releaseDate": "2018-01-01T00:00:00Z",
             "updateDate": "", "accessRights": None, "frequency": None, "version": None,
             "publisher_id": "agent-1"},
            # catalogue 114 is not registered in odms -> excluded
            {"dataset_id": "roma-114", "nodeID": "114", "title": "Roma", "description": "x",
             "landingPage": None, "releaseDate": None, "updateDate": None, "accessRights": None,
             "frequency": None, "version": None, "publisher_id": None},
        ],
        "distributions": [
            {"id": "d1", "dataset_id": "arbres-96", "nodeID": "96", "title": "", "description": None,
             "format": "CSV", "mediaType": "text/csv", "accessURL": "http://a/1", "downloadURL": "http://dl/1",
             "licenseDocument_id": "lic-1", "releaseDate": None, "updateDate": None, "byteSize": None},
            {"id": "d2", "dataset_id": "roma-114", "nodeID": "114", "title": "r", "description": None,
             "format": "XML", "mediaType": None, "accessURL": None, "downloadURL": None,
             "licenseDocument_id": None, "releaseDate": None, "updateDate": None, "byteSize": None},
        ],
        "keywords": [{"dataset_id": "arbres-96", "nodeID": "96", "keywords": "arbres"},
                     {"dataset_id": "arbres-96", "nodeID": "96", "keywords": "Arbres"},
                     {"dataset_id": "arbres-96", "nodeID": "96", "keywords": "nature"}],
        "themes": [{"concept_id": "c1", "dataset_id": "arbres-96", "nodeID": "96", "type": "1",
                    "value": "Environnement", "language": "fr"},
                   {"concept_id": "c1", "dataset_id": "arbres-96", "nodeID": "96", "type": "1",
                    "value": "Environment", "language": "en"}],
        "agent_names": [{"agent_id": "agent-1", "value": "Ville de Paris", "language": None}],
        "licenses": [{"licenseDocument_id": "lic-1", "name": "Open Database License (ODbL)", "uri": "http://odbl"}],
    }


def test_clean_text_strips_html_and_keeps_paragraphs():
    out = repo.clean_text("<p>Hello <b>world</b> &amp; co</p><p>Second</p>")
    assert out == "Hello world & co\nSecond"
    assert repo.clean_text(None) == ""


def test_build_entities_shapes_dataset_like_ngsi():
    entities = repo.build_entities(_rows())
    ids = {e["_id"]["id"] for e in entities}
    assert ids == {"arbres-96", "d1"}  # node 114 excluded with its distribution

    ds = next(e for e in entities if e["_id"]["id"] == "arbres-96")
    assert get_entity_type(ds) == "Dataset"
    a = extract_attrs(ds)
    assert a["Title"] == "Les arbres"
    assert "<" not in a["Description"] and "arbres & jardins" in a["Description"]
    assert a["Keywords"] == "arbres, nature"          # case-insensitive dedupe
    assert a["Theme"] == "Environment"                # preferred language
    assert a["Publisher"] == "Ville de Paris"
    assert a["LandingPage"] == "http://opendata.paris.fr/arbres"
    assert a["Catalogue"] == "Paris Open Data"
    assert a["DistributionIds"] == "d1"
    assert "Updated" not in a                         # empty values dropped
    assert all(v["value"] not in (None, "None") for v in ds["attrs"].values())


def test_build_entities_distribution_is_linked_and_has_dataset_context():
    entities = repo.build_entities(_rows())
    dist = next(e for e in entities if e["_id"]["id"] == "d1")
    assert get_entity_type(dist) == "DistributionDCAT-AP"
    a = extract_attrs(dist)
    assert a["BelongsToDataset"] == "arbres-96"
    assert a["URL"] == "http://dl/1"
    assert a["License"] == "Open Database License (ODbL)"
    assert a["Title"] == "Les arbres (CSV, text/csv)"
    assert "Les arbres" in a["Description"] or "Les arbres" in a["Title"]

    info = build_distribution_info(entities)
    assert info["arbres-96"]["formats"] == ["CSV"]
    assert info["arbres-96"]["url"] == "http://dl/1"
    assert info["arbres-96"]["license"] == "Open Database License (ODbL)"


def test_build_entities_include_unregistered_when_disabled():
    with patch.object(repo, "ONLY_REGISTERED", False):
        ids = {e["_id"]["id"] for e in repo.build_entities(_rows())}
    assert {"roma-114", "d2"} <= ids


def test_content_hash_changes_with_content():
    e = repo.build_entities(_rows())[0]
    h1 = content_hash(e)
    e["attrs"]["title"]["value"] = "Changed"
    assert content_hash(e) != h1


@pytest.mark.asyncio
async def test_get_all_dataset_ids_filters_unregistered_nodes():
    rows = {"catalogues": [{"id": 96}],
            "datasets": [{"dataset_id": "a-96", "nodeID": "96"}, {"dataset_id": "b-114", "nodeID": "114"}],
            "distributions": [{"id": "d1", "dataset_id": "a-96", "nodeID": "96"},
                              {"id": "d2", "dataset_id": "b-114", "nodeID": "114"}]}
    with patch.object(repo, "fetch_many", new=AsyncMock(return_value=rows)):
        ids = await repo.get_all_dataset_ids("t")
    assert sorted(ids) == ["a-96", "d1"]


def test_parse_sources():
    from app.ingestion.sources import _parse_sources
    assert _parse_sources("mysql, mongo_nbs") == ["mysql", "mongo_nbs"]
    assert _parse_sources("") == ["mongo"]
    assert _parse_sources("mongo,mongo_nbs") == ["mongo"]
    with pytest.raises(ValueError):
        _parse_sources("postgres")


@pytest.mark.asyncio
async def test_incremental_skips_unchanged_and_removes_stale():
    from app.ingestion import service

    entities = repo.build_entities(_rows())
    dinfo = build_distribution_info(entities)
    ds = next(e for e in entities if e["_id"]["id"] == "arbres-96")
    indexed = {"arbres-96": content_hash(ds, dinfo.get("arbres-96")),  # unchanged
               "d1": "old-hash",                                        # changed
               "urn:ngsi-ld:Dataset:old": "x"}                          # stale

    collection = MagicMock()
    with patch.object(service, "get_indexed_hashes", return_value=indexed), \
         patch.object(service, "get_tenant_collection", return_value=collection), \
         patch.object(service, "get_datasets_since", new=AsyncMock(return_value=entities)), \
         patch.object(service, "get_deleted_dataset_ids", new=AsyncMock(return_value=[])), \
         patch.object(service, "get_all_dataset_ids", new=AsyncMock(return_value=["arbres-96", "d1"])), \
         patch.object(service, "build_payload", new=AsyncMock(return_value="text")), \
         patch.object(service, "generate_embedding", new=AsyncMock(return_value=[0.1] * 4)), \
         patch.object(service, "delete_documents_from_collection") as mock_delete:
        result = await service.ingest_tenant("t")

    assert result["unchanged"] == 1
    assert result["total_datasets"] == 1
    deleted = [c.args[1] for c in mock_delete.call_args_list]
    assert ["urn:ngsi-ld:Dataset:old"] in deleted   # stale removed
    assert ["d1"] in deleted                         # old chunks of changed entity
    upserted = collection.upsert.call_args.kwargs
    assert upserted["ids"] == ["d1_chunk_1"]
    assert upserted["metadatas"][0]["content_hash"] != "old-hash"
    assert upserted["metadatas"][0]["source"] == "idra-mysql"
