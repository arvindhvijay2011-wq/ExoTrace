"""Offline tests for ExoTrace vector corpus construction."""

from __future__ import annotations

import pandas as pd

from exotrace.vector.build_corpus import (
    build_corpus_documents,
    chunk_reference_text,
    chunk_words,
)


def test_chunk_words_creates_overlapping_chunks() -> None:
    words = [f"token{i}" for i in range(25)]
    chunks = chunk_words(" ".join(words), chunk_words=10, overlap_words=3)

    assert len(chunks) == 4
    assert chunks[0].split()[-3:] == chunks[1].split()[:3]
    assert chunks[1].split()[-3:] == chunks[2].split()[:3]
    assert chunks[-1].split()[-1] == "token24"


def test_chunk_words_rejects_invalid_overlap() -> None:
    try:
        chunk_words("some text", chunk_words=5, overlap_words=5)
    except ValueError as exc:
        assert "overlap_words" in str(exc)
    else:
        raise AssertionError("Expected invalid overlap to be rejected.")


def test_profiles_preserve_missing_measurements_and_insolation_caution() -> None:
    frame = pd.DataFrame(
        [
            {
                "pl_name": "Example b",
                "hostname": "Example Star",
                "discoverymethod": "Imaging",
                "disc_year": 2024,
                "disc_facility": "Example Observatory",
                "pl_orbper": None,
                "pl_orbpererr1": None,
                "pl_orbpererr2": None,
                "pl_orbsmax": 10.0,
                "pl_rade": 3.0,
                "pl_bmasse": None,
                "pl_eqt": 0.0,
                "pl_orbeccen": None,
                "pl_insol": 0.0,
                "pl_insol_reflink": '<a refstr="CALCULATED_VALUE">Calculated Value</a>',
                "st_teff": 4000.0,
                "st_rad": 0.8,
                "st_mass": 0.7,
                "sy_dist": 15.0,
            }
        ]
    )
    docs = build_corpus_documents(
        frame,
        [],
        snapshot_id="PSCompPars::samplehash",
        source_file="data/raw/sample.csv",
        source_sha256="samplehash",
    )
    profile = docs[0]

    assert profile["doc_type"] == "planet_profile"
    assert profile["metadata"]["record_id"] == "PSCompPars::samplehash::Example b"
    assert profile["metadata"]["insolation_quality_status"] == "calculated_zero_requires_caution"
    assert "Orbital period" in profile["text"]
    assert "No value reported in this catalogue record" in profile["text"]
    assert "do not silently interpret it as a validated physical zero" in profile["text"]
    assert "0.0 days" not in profile["text"]


def test_reference_chunks_preserve_source_metadata_and_ids() -> None:
    frame = pd.DataFrame([{"pl_name": "Example b", "hostname": "Example Star"}])
    pages = [
        {
            "doc_id": "reference:detection_methods",
            "slug": "detection_methods",
            "title": "Detection Methods",
            "url": "https://science.nasa.gov/exoplanets/how-we-find-and-characterize/",
            "publisher": "science.nasa.gov",
            "text": " ".join(f"scientificword{i}" for i in range(410)),
            "raw_file": "data/raw/reference_pages/detection_methods.html",
            "raw_sha256": "rawhash",
            "text_sha256": "texthash",
        }
    ]
    docs = build_corpus_documents(
        frame,
        pages,
        snapshot_id="PSCompPars::samplehash",
        source_file="data/raw/sample.csv",
        source_sha256="samplehash",
    )
    reference_docs = [doc for doc in docs if doc["doc_type"] == "official_nasa_reference_chunk"]

    assert len(reference_docs) == 2
    assert reference_docs[0]["metadata"]["source_url"] == pages[0]["url"]
    assert reference_docs[0]["metadata"]["source_type"] == "official_nasa_reference"
    assert reference_docs[0]["doc_id"].startswith("reference:detection_methods:chunk:")


def test_reference_chunking_preserves_section_boundaries() -> None:
    text = "\n\n".join(
        [
            "In Depth - NASA Science",
            "How We Find Exoplanets?",
            "Astronomers observe stars over time and measure changes in their light. "
            "These observations can reveal the presence of an orbiting planet.",
            "Radial Velocity: Reading the Wobble",
            "A planet's gravity pulls on its star, causing the star to move slightly. "
            "Astronomers detect the movement through changes in the star's spectrum.",
            "Transits: Planets Found in Dips in Light",
            "A planet passing in front of its star blocks some of the starlight. "
            "The measured brightness drops during the transit.",
        ]
    )

    chunks = chunk_reference_text(text, page_title="How NASA Finds Exoplanets")

    radial_chunks = [
        chunk for chunk in chunks
        if chunk["section_heading"] == "Radial Velocity: Reading the Wobble"
    ]
    transit_chunks = [
        chunk for chunk in chunks
        if chunk["section_heading"] == "Transits: Planets Found in Dips in Light"
    ]
    assert radial_chunks
    assert transit_chunks
    assert all("star's spectrum" in chunk["body"] for chunk in radial_chunks)
    assert all("brightness drops" in chunk["body"] for chunk in transit_chunks)
    assert "In Depth - NASA Science" not in " ".join(chunk["body"] for chunk in chunks)


def test_reference_chunk_metadata_includes_section_heading_and_version() -> None:
    frame = pd.DataFrame([{"pl_name": "Example b", "hostname": "Example Star"}])
    pages = [
        {
            "doc_id": "reference:detection_methods",
            "slug": "detection_methods",
            "title": "In Depth - NASA Science",
            "url": "https://science.nasa.gov/exoplanets/how-we-find-and-characterize/",
            "publisher": "science.nasa.gov",
            "text": "Radial Velocity: Reading the Wobble\n\n"
            "A planet tugs its host star and causes a measurable wobble in the star's spectrum.",
            "raw_file": "data/raw/reference_pages/detection_methods.html",
            "raw_sha256": "rawhash",
            "text_sha256": "texthash",
        }
    ]
    docs = build_corpus_documents(
        frame,
        pages,
        snapshot_id="PSCompPars::samplehash",
        source_file="data/raw/sample.csv",
        source_sha256="samplehash",
    )
    reference_docs = [
        doc for doc in docs if doc["doc_type"] == "official_nasa_reference_chunk"
    ]
    assert len(reference_docs) == 1
    assert reference_docs[0]["title"] == "How NASA Finds and Characterizes Exoplanets"
    assert reference_docs[0]["metadata"]["section_heading"] == "Radial Velocity: Reading the Wobble"
    assert reference_docs[0]["metadata"]["chunking_version"] == "paragraph_section_v2"
