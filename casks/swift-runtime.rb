# Copied from https://github.com/thii/homebrew-swift-runtime/blob/master/Casks/swift-runtime.rb
#
# Install the Swift Runtime tools, necessary to statically link
# Swift applications on the older Macs available as GitHub runners.
cask 'swift-runtime' do
  version '061-41823-20191025-5efc5a59-d7dc-46d3-9096-396bb8cb4a73'
  sha256 'd5956aa3c543cdb6e0031f63c3d6a04b149e341c2dccfe917e794912015650ca'

  url "https://updates.cdn-apple.com/2019/cert/#{version}/SwiftRuntimeForCommandLineTools.dmg"
  name 'Swift Runtime Support For Command Line Tools'
  homepage 'https://support.apple.com/kb/DL1998'

  pkg 'SwiftRuntimeForCommandLineTools.pkg'

  uninstall pkgutil: 'com.apple.pkg.SwiftRuntimeForCommandLineTools'
end
