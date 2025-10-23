Vagrant.configure("2") do |config|

    config.vm.box = "bento/ubuntu-22.04"

    config.vm.network "forwarded_port", guest: 5000, host: 5000
    
    config.vm.hostname = "projeto2"

    config.vm.synced_folder "./web-server", "/home/vagrant/web-server"

    config.vm.provider "virtualbox" do |vb|
        vb.gui = false
        vb.memory = "4096"
        vb.cpus = 4
        vb.name = "projeto2"
    end
  config.vm.provision "shell", path: "setup.sh", privileged: true, args: "--debug" # Adicionado --debug para mais output
end
