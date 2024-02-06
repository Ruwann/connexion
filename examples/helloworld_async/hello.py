from pathlib import Path

import connexion
from starlette.responses import StreamingResponse
import vertexai
from vertexai.language_models import TextGenerationModel


async def test():
    pass


async def post_greeting(name: str):
    """Streaming Text Example with a Large Language Model"""
    project_id = ""
    location = "europe-west1"
    vertexai.init(project=project_id, location=location)

    text_generation_model = TextGenerationModel.from_pretrained("text-bison")
    parameters = {
        "temperature": 1,  # Temperature controls the degree of randomness in token selection.
        "max_output_tokens": 256,  # Token limit determines the maximum amount of text output.
        "top_p": 0.8,  # Tokens are selected from most probable to least until the sum of their probabilities equals the top_p value.
        "top_k": 40,  # A top_k of 1 means the selected token is the most probable among all tokens.
    }

    # text_generation_model.predict_async()
    def generate_text():
        responses = text_generation_model.predict_streaming(
            prompt="Give me ten interview questions for the role of program manager.",
            **parameters,
        )
        for response in responses:
            yield response.text

    return StreamingResponse(generate_text(), media_type="text/plain")


app = connexion.AsyncApp(__name__, specification_dir="spec")
app.add_api("openapi.yaml", arguments={"title": "Hello World Example"})
app.add_api("swagger.yaml", arguments={"title": "Hello World Example"})


if __name__ == "__main__":
    app.run(f"{Path(__file__).stem}:app", port=8080)
