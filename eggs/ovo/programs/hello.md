---
name: hello
program_type: prompt
includes:
  - identity
tools:
  - memory get
  - memory put
triggers:
  - pattern: "channel.message"
    priority: 10
metadata:
  description: "A simple greeting program"
---
You are a helpful assistant. Greet the user and ask how you can help.
