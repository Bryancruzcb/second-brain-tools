import os
import sys
import chromadb
from sentence_transformers import SentenceTransformer

def main():
    if len(sys.argv) < 2:
        print("Usage: python rag_query.py \"Your question here\"")
        sys.exit(1)
        
    query = " ".join(sys.argv[1:])
    
    home_dir = os.path.expanduser("~")
    db_path = os.path.join(home_dir, "IdeaProjects/second-brain-tools/chroma_db")
    
    if not os.path.exists(db_path):
        print(f"Error: Vector database not found at {db_path}.")
        print("Please run rebuild_rag_index.py first.")
        sys.exit(1)
        
    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_collection("second_brain")
    
    # We load the embedding model to encode the query
    model = SentenceTransformer('all-MiniLM-L6-v2')
    query_embedding = model.encode([query]).tolist()
    
    print(f"🔍 Searching Vector Database for: '{query}'...")
    
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=3
    )
    
    print("\n--- 🧠 TOP KNOWLEDGE RETRIEVALS ---")
    
    context = ""
    for i in range(len(results['documents'][0])):
        doc = results['documents'][0][i]
        meta = results['metadatas'][0][i]
        title = meta['title']
        source = meta['source']
        distance = results['distances'][0][i]
        
        print(f"\n📄 {title} (Distance: {distance:.4f})")
        print(f"Path: {source}")
        print(f"Content Snippet: {doc[:300]}...")
        
        context += f"From Note: {title}\n{doc}\n\n"
        
    print("\n--- 🤖 AI PROMPT ---\n")
    print("If you were to pass this to an LLM like GPT-4 or Gemini, the system prompt would be:")
    print("--------------------------------------------------")
    print(f"You are a Second Brain Assistant. Answer the user's question using ONLY the provided context.\n\nContext:\n{context}\nQuestion: {query}")
    print("--------------------------------------------------")

if __name__ == "__main__":
    main()
