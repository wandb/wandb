package kjobs

import (
	"context"
	"fmt"

	"github.com/spf13/cobra"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
)

// CreateKubernetesJob creates a new Kubernetes Job with the given parameters
func CreateKubernetesJob(clientset *kubernetes.Clientset, namespace string, jobName string, image string, command []string) (*batchv1.Job, error) {
	job := &batchv1.Job{
		ObjectMeta: metav1.ObjectMeta{
			Name: jobName,
		},
		Spec: batchv1.JobSpec{
			Template: corev1.PodTemplateSpec{
				Spec: corev1.PodSpec{
					RestartPolicy: corev1.RestartPolicyNever,
					Containers: []corev1.Container{
						{
							Name:    jobName,
							Image:   image,
							Command: command,
						},
					},
				},
			},
		},
	}

	createdJob, err := clientset.BatchV1().
		Jobs(namespace).
		Create(context.Background(), job, metav1.CreateOptions{})
	if err != nil {
		return nil, fmt.Errorf("failed to create job: %w", err)
	}

	return createdJob, nil
}

func NewKJobsCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "kubernetes-jobs",
		Short: "Execute Kubernetes jobs when jobs are received",
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}
}
