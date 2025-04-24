package kubernetes

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/charmbracelet/log"
	"github.com/spf13/cobra"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
)

func NewSyncKubernetesCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "kubernetes",
		Short: "Sync Kubernetes resources on a cluster",
		Example: heredoc.Doc(`
			$ ctrlc sync kubernetes --cluster 1234567890
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			log.Info("Syncing Kubernetes resources on a cluster")
			config, clusterName, err := getKubeConfig()
			if err != nil {
				return err
			}

			log.Info("Connected to cluster", "name", clusterName)

			clientset, err := kubernetes.NewForConfig(config)
			if err != nil {
				return err
			}

			pods, err := clientset.CoreV1().Pods("default").List(
				context.Background(), metav1.ListOptions{})
			if err != nil {
				return err
			}

			if len(pods.Items) > 0 {
				log.Info("First two pods:")
				for i := 0; i < min(2, len(pods.Items)); i++ {
					pod := pods.Items[i]
					podJson, err := json.Marshal(pod)
					if err != nil {
						log.Error("Failed to marshal pod to JSON", "error", err)
						continue
					}
					fmt.Println(string(podJson))
					// log.Info("Pod", "json", string(podJson))
				}
			} else {
				log.Info("No pods found in default namespace")
			}

			return nil
		},
	}

	cmd.Flags().String("cluster", "", "The cluster to sync")

	return cmd
}
