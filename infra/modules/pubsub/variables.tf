variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "topics" {
  description = <<-EOT
    Map of topic_name => spec. Spec fields:
      - message_retention_duration : ISO-8601 duration (default '604800s' = 7d)
      - publishers   : IAM members getting roles/pubsub.publisher on the topic
      - subscribers  : IAM members getting roles/pubsub.subscriber on the topic
                       (Pub/Sub subscriber role is normally bound at the subscription
                       level, but binding it at the topic level lets the worker create
                       its own subscription later. Optional.)
  EOT
  type = map(object({
    message_retention_duration = optional(string, "604800s")
    publishers                 = optional(list(string), [])
    subscribers                = optional(list(string), [])
  }))
}

variable "labels" {
  description = "Labels propagated to topics."
  type        = map(string)
  default     = {}
}
