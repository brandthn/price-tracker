output "topics" {
  description = "Map of topic_name => { id, name }."
  value = {
    for k, t in google_pubsub_topic.this : k => {
      id   = t.id
      name = t.name
    }
  }
}

output "topic_ids" {
  description = "Map of topic_name => fully qualified ID (projects/.../topics/...)."
  value       = { for k, t in google_pubsub_topic.this : k => t.id }
}
