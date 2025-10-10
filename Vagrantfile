Vagrant.configure("2") do |config|
config.vm.network "forwarded_port", guest: 50, host: 8080
config.vm.box = "bento/ubuntu-22.04"
config.vm.hostname = "lab-cgroup"
config.vm.provider "virtualbox" do |vb|
vb.gui = false
vb.memory = "4096"
vb.cpus = 4
vb.name = "lab-cgroup"
end
end
