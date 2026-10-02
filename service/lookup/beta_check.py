"""Exercise the researcher-facing port, including a real semantic request."""

import argparse
import json

import httpx


def check(url: str) -> dict:
    """Require editor, lexical typo results, and actual semantic results."""
    with httpx.Client(base_url=url, timeout=120) as client:
        editor = client.get("/")
        editor.raise_for_status()
        if "<html" not in editor.text.lower():
            raise ValueError("Preview did not serve the editor HTML")
        health = client.get("/api/v1/mvp/triad/health")
        health.raise_for_status()
        status = health.json()
        if status["total_terms"] != 75876:
            raise ValueError("Unexpected beta catalog")
        lexical = client.get("/api/v1/mvp/triad/lexical", params={"q": "snoil", "limit": 5})
        lexical.raise_for_status()
        if not any(row["label"].lower() == "soil" for row in lexical.json()["results"]):
            raise ValueError("Typo lookup did not find soil")
        semantic = client.get(
            "/api/v1/mvp/triad/semantic", params={"q": "desert environment", "limit": 5}
        )
        semantic.raise_for_status()
        rows = semantic.json()["results"]
        if not rows or not all(row["match_method"] == "semantic" for row in rows):
            raise ValueError("Semantic lookup returned no actual semantic results")
        return {
            "status": "passed",
            "total_terms": status["total_terms"],
            "semantic": rows[0]["curie"],
        }


def main() -> None:
    """Run the beta acceptance smoke check against a configurable URL."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8088")
    args = parser.parse_args()
    print(json.dumps(check(args.url), sort_keys=True))


if __name__ == "__main__":
    main()
