Vagrant.configure("2") do |config|

    config.vm.box = "bento/ubuntu-22.04"

    config.vm.network "forwarded_port", guest: 5000, host: 8080
    
    config.vm.hostname = "projeto2"

    config.vm.synced_folder "web-server", "/var/www/html", owner: "vagrant", group: "www-data", mount_options: ["dmode=775", "fmode=664"]


    config.vm.provider "virtualbox" do |vb|
        vb.gui = false
        vb.memory = "4096"
        vb.cpus = 4
        vb.name = "projeto2"
    end
    config.vm.provision "shell", path: "setup.sh"
end
