output "datasets" {
  description = "Map of dataset_id => { id, self_link }."
  value = {
    for k, ds in google_bigquery_dataset.this : k => {
      id         = ds.id
      dataset_id = ds.dataset_id
      self_link  = ds.self_link
      location   = ds.location
      project    = ds.project
      qualified  = "${ds.project}.${ds.dataset_id}"
    }
  }
}
