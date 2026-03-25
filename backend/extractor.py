
# import os
# from dotenv import load_dotenv
# from azure.ai.documentintelligence import DocumentIntelligenceClient
# from azure.core.credentials import AzureKeyCredential

# load_dotenv()

# client = DocumentIntelligenceClient(
#     endpoint = os.getenv("AZURE_DOC_INTELLIGENCE_ENDPOINT"),
#     credential=AzureKeyCredential(os.getenv("AZURE_DOC_INTELLIGENCE_KEY"))
# )
    
# async def extract_from_image(image_bytes: bytes) -> dict: 
#     poller = await client.begin_analyze_document(
#         model_id="prebuilt-document",
#         analyze_request=image_bytes,
#     )
    
#     result = poller.result()
    
#     words = []
    
#     for page in result.pages:
#         for word in page.words:
#             words.append({
#                 "text": word.content,
#                 "Confidence": round(word.confidence, 2)
#             })
    
#     full_text = " ".join(w["text"] for w in words)
    
#     return {
#         "full words": full_text,
#         "words": words,
#         "page_count": len(results.pages)
#     }
    
    
    
    
    
    
    
import os
import asyncio
from dotenv import load_dotenv
from azure.ai.documentintelligence.aio import DocumentIntelligenceClient  # async client
from azure.core.credentials import AzureKeyCredential

load_dotenv()

client = DocumentIntelligenceClient(
    endpoint=os.getenv("AZURE_DOC_INTELLIGENCE_ENDPOINT"),
    credential=AzureKeyCredential(os.getenv("AZURE_DOC_INTELLIGENCE_KEY"))
)

def extract_from_image(image_bytes: bytes) -> dict:
    poller =  client.begin_analyze_document(
        model_id="prebuilt-document",
        body=image_bytes,                          # fix 1: was analyze_request
        content_type="application/octet-stream"   # fix 2: required for raw bytes
    )

    result =  poller.result()                 # fix 3: poller.result() is also async

    words = []
    for page in result.pages:
        for word in page.words:
            words.append({
                "text": word.content,
                "confidence": round(word.confidence, 2)
            })

    full_text = " ".join(w["text"] for w in words)

    return {
        "full_text": full_text,
        "words": words,
        "page_count": len(result.pages)            # fix 4: was results.pages (typo)
    }
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    