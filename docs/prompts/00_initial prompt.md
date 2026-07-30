Act as a senior software engineer. 

You are building a product for first-year university students in English 101 and English 102 courses. They write five paragraph essays [Introduction, Body Paragraphs, Conclusion]. 

The product is called Write Like a Reader: and is described in `docs/write_like_a_reader.md`.

As a senior software engineer, you will use python and gradio to create a web based app where the student can upload their writing, receive feedback, incorporate their feedback, and download the updated draft. 

You need to create at least two agents: 1 agent that reads the student's writing and asks questions. 

The other agent will decide if those questions are worth asking by identifying if the student answers the question in the next sentence. 

You need to decide what framework to use: Ollama, HuggingFace, or recommend something else. Note, there is a hugging face token in `.env` file and the token has the variable name `HF_TOKEN` so it can be loaded with the `dotenv` package from python. 

Create an HTML for your questions so it is easier for me to read your questions and feedback. 

We are starting in plan mode so ask me ALL the questions you need. 