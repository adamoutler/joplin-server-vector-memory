#!/bin/bash
echo "Firing 3 concurrent requests to Ollama..."

start=$(date +%s%3N)

curl -s -X POST http://192.168.1.101:11434/api/embeddings -d '{"model": "embeddinggemma:300m", "prompt": "This is test document number 1. It is a bit longer to simulate a real embedding payload."}' -o /dev/null &
pid1=$!

curl -s -X POST http://192.168.1.101:11434/api/embeddings -d '{"model": "embeddinggemma:300m", "prompt": "This is test document number 2. It is a bit longer to simulate a real embedding payload."}' -o /dev/null &
pid2=$!

curl -s -X POST http://192.168.1.101:11434/api/embeddings -d '{"model": "embeddinggemma:300m", "prompt": "This is test document number 3. It is a bit longer to simulate a real embedding payload."}' -o /dev/null &
pid3=$!

wait $pid1
echo "Request 1 finished"
wait $pid2
echo "Request 2 finished"
wait $pid3
echo "Request 3 finished"

end=$(date +%s%3N)
echo "Total time: $((end-start)) ms"
