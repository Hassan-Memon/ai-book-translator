# AI Book Translator — Urdu to Arabic with Context-Aware LLMs
An AI-powered Urdu to Arabic book translator that intelligently processes documents (PDF, Word, Excel, or images), chunks content based on structure, and uses multi-stage LLM agents to ensure accurate, context-aware, and faithful translation without omissions or additions.


have to create an Urdu to Arabic Translation Agent, that will take a file in pdf/doc/docs/excel (or image) format and it will:
- read the document 
- chunking using smart and new chunking tequniuques on paraghps and and haddings
- have there should have sevral nodes each responsible for specific task:
	* translating the chunk word by word must sure it not miss or add any thing throw llm
	* correct the word by word translation and make it near to the Arabic Context and style but stic to 		the orginal content, no addition and no missing.
	* comparision between orginal content in Urdu (along with two neighbor chunks in Urdu or we can do 		this step in the next separate step) correct Arabic translation
			-> if it pass the thereshlod like 80% or 90% it can be dicede after tests so it mark it as correct transtlation and proceed to the next step else mark it as bad and repete the cycle from correction step which is second step.
	