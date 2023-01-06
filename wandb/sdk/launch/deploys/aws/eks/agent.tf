resource "kubernetes_namespace" "wandb" {
  metadata {
    name = "wandb"

    labels = {
      "pod-security.kubernetes.io/enforce" = "baseline"

      "pod-security.kubernetes.io/enforce-version" = "latest"

      "pod-security.kubernetes.io/warn" = "baseline"

      "pod-security.kubernetes.io/warn-version" = "latest"
    }
  }
}

resource "kubernetes_role" "wandb_launch_agent" {
  metadata {
    name      = "wandb-launch-agent"
    namespace = "wandb"
  }

  rule {
    verbs      = ["create", "get", "watch", "list", "update", "delete", "patch"]
    api_groups = [""]
    resources  = ["pods", "configmaps", "secrets", "pods/log"]
  }

  rule {
    verbs      = ["create", "get", "watch", "list", "update", "delete", "patch"]
    api_groups = ["batch"]
    resources  = ["jobs", "jobs/status"]
  }
}

resource "kubernetes_cluster_role" "job_creator" {
  metadata {
    name = "job-creator"
  }

  rule {
    verbs      = ["create", "get", "watch", "list", "update", "delete", "patch"]
    api_groups = [""]
    resources  = ["pods", "pods/log", "secrets"]
  }

  rule {
    verbs      = ["create", "get", "watch", "list", "update", "delete", "patch"]
    api_groups = ["batch"]
    resources  = ["jobs", "jobs/status"]
  }
}

resource "kubernetes_service_account" "wandb_launch_serviceaccount" {
  metadata {
    name      = "wandb-launch-serviceaccount"
    namespace = "wandb"
  }
}

resource "kubernetes_role_binding" "wandb_launch_role_binding" {
  metadata {
    name      = "wandb-launch-role-binding"
    namespace = "wandb"
  }

  subject {
    kind      = "ServiceAccount"
    name      = "wandb-launch-serviceaccount"
    namespace = "wandb"
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = "wandb-launch-agent"
  }
}

resource "kubernetes_role_binding" "wandb_launch_cluster_role_binding" {
  metadata {
    name      = "wandb-launch-cluster-role-binding"
    namespace = "default"
  }

  subject {
    kind      = "ServiceAccount"
    name      = "wandb-launch-serviceaccount"
    namespace = "wandb"
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = "job-creator"
  }
}

resource "kubernetes_config_map" "wandb_launch_configmap" {
  metadata {
    name      = "wandb-launch-configmap"
    namespace = "wandb"
  }

  data = {
    "launch-config.yaml" = <<EOT
base_url: https://api.wandb.ai # TODO: set wandb base url
max_jobs: 10
project: model-registry
entity: bcanfieldsherman
queues: [kubernetes]
registry:
  url: 
  ecr-provider: aws
  region: us-east-2
build:
  type: kaniko
  cloud-provider: aws
  build-context-store:  # name here
runner: # this can be set to specify default runner configuration
  type: kubernetes
  namespace: default
EOT
  }
}

resource "kubernetes_secret" "wandb_api_key" {
  metadata {
    name      = "wandb-api-key"
    namespace = "wandb"
  }
  data = {
    password = ""
  }
  type = "kubernetes.io/basic-auth"

}

resource "kubernetes_deployment" "launch_agent" {
  metadata {
    name      = "launch-agent"
    namespace = "wandb"
  }
  spec {
    replicas = 1
    selector {
      match_labels = {
        app = "launch-agent"
      }
    }

    template {
      metadata {
        labels = {
          app = "launch-agent"
        }
      }

      spec {
        volume {
          name = "wandb-launch-config"

          config_map {
            name = "wandb-launch-configmap"
          }
        }

        container {
          name  = "launch-agent"
          image = "wandb/launch-agent-dev:939c8c754b"

          env {
            name = "WANDB_API_KEY"

            value_from {
              secret_key_ref {
                name = "wandb-api-key"
                key  = "password"
              }
            }
          }

          resources {
            limits = {
              cpu = "1"

              memory = "2Gi"
            }
          }

          volume_mount {
            name       = "wandb-launch-config"
            read_only  = true
            mount_path = "/home/launch_agent/.config/wandb"
          }

          security_context {
            capabilities {
              drop = ["ALL"]
            }

            run_as_user     = 1000
            run_as_non_root = true
          }
        }

        service_account_name = "wandb-launch-serviceaccount"
      }
    }
  }
}

