/**
# Copyright 2023 NVIDIA CORPORATION
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
**/

package nvml

// ExtendedInterface defines a set of extensions to the core NVML API.
//
// TODO: For now the list of methods in this interface need to be kept in sync
// with the list of excluded methods for the Interface type in
// gen/nvml/generateapi.go. In the future we should automate this.
//
//go:generate moq -out mock/extendedinterface.go -pkg mock . ExtendedInterface:ExtendedInterface
type ExtendedInterface interface {
	LookupSymbol(string) error
}

// libraryOptions hold the paramaters than can be set by a LibraryOption
type libraryOptions struct {
	path  string
	flags int
}

// LibraryOption represents a functional option to configure the underlying NVML library
type LibraryOption func(*libraryOptions)

// WithLibraryPath provides an option to set the library name to be used by the NVML library.
func WithLibraryPath(path string) LibraryOption {
	return func(o *libraryOptions) {
		o.path = path
	}
}

// SetLibraryOptions applies the specified options to the NVML library.
// If this is called when a library is already loaded, an error is raised.
func SetLibraryOptions(opts ...LibraryOption) error {
	libnvml.Lock()
	defer libnvml.Unlock()
	if libnvml.refcount != 0 {
		return errLibraryAlreadyLoaded
	}
	libnvml.init(opts...)
	return nil
}
