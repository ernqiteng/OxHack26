import pytest


@pytest.fixture(autouse=True)
def _clear_streamlit_caches():
    """st.cache_resource outlives a single AppTest run; clear it so each test picks its own source."""
    import streamlit as st

    st.cache_resource.clear()
    st.cache_data.clear()
    yield
    st.cache_resource.clear()
