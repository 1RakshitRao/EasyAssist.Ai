"""Standalone Groq API smoke test — run before wiring LangGraph."""



from __future__ import annotations



import sys

from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:

    sys.path.insert(0, str(ROOT))



from dotenv import load_dotenv



load_dotenv(ROOT / ".env")



from langchain_groq import ChatGroq  # noqa: E402



from app.config import get_settings  # noqa: E402





def main() -> None:

    settings = get_settings()

    if not settings.groq_api_key:

        raise SystemExit("Set GROQ_API_KEY in .env before running this script.")



    fast_llm = ChatGroq(

        model=settings.groq_model_fast,

        api_key=settings.groq_api_key,

        temperature=0.1,

    )

    response = fast_llm.invoke(

        [

            ("system", "You are an HR assistant. Answer only from company policy."),

            ("human", "What is the standard notice period for resignation?"),

        ]

    )

    print("=== FAST TIER (gpt-oss-20b) ===")

    print(response.content)

    meta = getattr(response, "usage_metadata", None)

    if meta:

        print(f"Tokens: {meta}")



    powerful_llm = ChatGroq(

        model=settings.groq_model_balanced,

        api_key=settings.groq_api_key,

        temperature=0.1,

    )

    response2 = powerful_llm.invoke(

        [

            ("system", "You are an HR assistant."),

            (

                "human",

                "Explain the full maternity leave policy including pay and duration.",

            ),

        ]

    )

    print("\n=== POWERFUL TIER (gpt-oss-120b) ===")

    print(response2.content)

    meta2 = getattr(response2, "usage_metadata", None)

    if meta2:

        print(f"Tokens: {meta2}")





if __name__ == "__main__":

    main()

