package kubernetes

import (
	"os"
	"path/filepath"

	"github.com/charmbracelet/log"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
)

func getKubeConfig() (*rest.Config, string, error) {
    // First, try the KUBECONFIG environment variable
    kubeconfigPath := os.Getenv("KUBECONFIG")
    if kubeconfigPath != "" {
		log.Info("Loading kubeconfig from environment variable", "path", kubeconfigPath)
        config, err := clientcmd.BuildConfigFromFlags("", kubeconfigPath)
        if err != nil {
            return nil, "", err
        }
        context, err := getCurrentContextName(kubeconfigPath)
        return config, context, err
    }

    // Next, try the default location (~/.kube/config)
    homeDir, err := os.UserHomeDir()
    if err == nil {
        kubeconfigPath = filepath.Join(homeDir, ".kube", "config")
        if _, err := os.Stat(kubeconfigPath); err == nil {
			log.Info("Loading kubeconfig from home directory", "path", kubeconfigPath)
            config, err := clientcmd.BuildConfigFromFlags("", kubeconfigPath)
            if err != nil {
                return nil, "", err
            }
            context, err := getCurrentContextName(kubeconfigPath)
            return config, context, err
        }
    }

    // Finally, assume we're running in a cluster (inside pod)
    log.Info("Loading in-cluster kubeconfig")
    config, err := rest.InClusterConfig()
    if err != nil {
        return nil, "", err
    }
    
    // When running in-cluster, we can get the cluster name from the namespace file
    clusterName, err := getInClusterName()
    return config, clusterName, err
}

func getCurrentContextName(kubeconfigPath string) (string, error) {
    kubeconfig, err := clientcmd.LoadFromFile(kubeconfigPath)
    if err != nil {
        return "", err
    }
    return kubeconfig.CurrentContext, nil
}

func getInClusterName() (string, error) {
    // When running in a pod, you can read the namespace from the service account
    nsBytes, err := os.ReadFile("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
    if err != nil {
        return "unknown-cluster", nil // Return a default value if we can't determine the namespace
    }
    
    return string(nsBytes), nil
}