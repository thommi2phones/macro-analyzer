from macro_positioning.pipelines.run_pipeline import build_pipeline
from macro_positioning.ingestion.sample_sources import sample_context, sample_documents


def test_pipeline_generates_memo():
    pipeline = build_pipeline()
    result = pipeline.run(sample_documents(), context=sample_context())

    assert result.documents_ingested == 3
    assert result.theses_extracted >= 1
    assert result.validated_theses >= 1
    assert result.memo_id
