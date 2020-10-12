#!/usr/bin/python

"""Code created to be presented with the paper titled:
   "Rich Experimentation through Hybrid Physical-Virtual Software-Defined Wireless
   Networking Emulation"
   authors: Ramon dos Reis Fontes and Christian Esteve Rothenberg"""

"""Topology

             (2)ap2(3)
            /         \
          (3)          (2)
wlan1(2)phyap1          ap3(4)wlan0
          (4)          (3) 
            \          /
             (3)ap4(2)          """


from mininet.log import setLogLevel, info
from mininet.node import RemoteController
from mn_wifi.node import UserAP, physicalAP
from mn_wifi.net import Mininet_wifi
from mn_wifi.cli import CLI
from mn_wifi.link import wmediumd, mesh
from mn_wifi.wmediumdConnector import interference
import time


def topology():

    "Create a network."
    net = Mininet_wifi( controller=RemoteController, accessPoint=UserAP,
                        link=wmediumd, wmediumd_mode=interference )

    internetIface = 'enp3s0'
    usbDongleIface = 'wlxf4f26d193319'

    info("*** Creating nodes\n")
    for n in range(10):
        net.addStation('sta%s' % (n+1), wlans=2, mac='00:00:00:00:00:' + '%02x' % (n+1),
                       ip='192.168.0.%s/24' % (n+1))
    sta11 = net.addStation('sta11', ip='10.0.0.111/8', position='60,100,0')

    h12 = net.addHost('h12', ip='10.0.0.109/8')
    root = net.addHost('root', ip='10.0.0.254/8', inNamespace=False)

    phyap1 = net.addAccessPoint(
        'phyap1', protocols='OpenFlow13', ssid='Sigcomm-2016',
        mode='g', channel='1', position='50,115,0', phywlan=usbDongleIface,
        cls=physicalAP)
    ap2 = net.addAccessPoint( 'ap2', protocols='OpenFlow13', ssid='ap-ssid2',
                              mode='g', channel='11', position='100,175,0' )
    ap3 = net.addAccessPoint( 'ap3', protocols='OpenFlow13', ssid='ap-ssid3',
                              mode='g', channel='6', position='150,115,0' )
    ap4 = net.addAccessPoint( 'ap4', protocols='OpenFlow13', ssid='ap-ssid4',
                              mode='g', channel='11', position='100,55,0' )
    c5 = net.addController( 'c5', controller=RemoteController, port=6653 )

    info("*** Configuring Propagation Model\n")
    net.setPropagationModel(model="logDistance", exp=4)

    info("*** Configuring wifi nodes\n")
    net.configureWifiNodes()

    info("*** Creating links\n")
    for sta in net.stations:
        net.addLink(sta, cls=mesh, intf='%s-wlan0' % sta.name, ssid='meshNet')

    info("*** Associating and Creating links")
    net.addLink(phyap1, ap2)
    net.addLink(ap2, ap3)
    net.addLink(sta11, phyap1)
    net.addLink(ap3, ap4)
    net.addLink(ap4, phyap1)
    net.addLink(root, ap3)
    net.addLink(phyap1, h12)

    net.plotGraph(max_x=240, max_y=240)

    net.setMobilityModel(time=0, model='RandomWalk', max_x=200,
                         max_y=200, min_v=0.1, max_v=0.2, seed=20)

    info("*** Starting network\n")
    net.build()
    c5.start()
    phyap1.start( [c5] )
    ap2.start( [c5] )
    ap3.start( [c5] )
    ap4.start( [c5] )

    time.sleep(2)
    'output=all,flood'
    ap3.cmd('dpctl unix:/tmp/ap3 meter-mod cmd=add,flags=1,meter=1 drop:rate=100')
    ap3.cmd('dpctl unix:/tmp/ap3 flow-mod table=0,cmd=add in_port=4,eth_type=0x800,ip_dst=10.0.0.100,meter:1 apply:output=flood')
    phyap1.cmd('dpctl unix:/tmp/phyap1 flow-mod table=0,cmd=add in_port=2,ip_dst=10.0.0.109,eth_type=0x800,ip_proto=6,tcp_dst=80 apply:set_field=tcp_dst:80,set_field=ip_dst:10.0.0.111,output=5')
    phyap1.cmd('dpctl unix:/tmp/phyap1 flow-mod table=0,cmd=add in_port=1,eth_type=0x800,ip_proto=6,tcp_src=80 apply:set_field=ip_src:10.0.0.109,output=2')

    fixNetworkManager( root, 'root-eth0' )

    startNAT(root, internetIface)

    sta11.cmd('ip route add default via 10.0.0.254')
    sta11.cmd('pushd /home/fontes; python3 -m http.server 80 &')

    for id, sta in enumerate(net.stations):
        if sta.name != 'sta11':
            sta.setIP('10.0.0.%s/8' % (id+201), intf="%s-wlan1" % sta)
            sta.cmd('ip route add default via 10.0.0.254')

    info("*** Running CLI\n")
    CLI( net )

    info("*** Stopping network\n")
    net.stop()


def startNAT( root, inetIntf, subnet='10.0/8', localIntf = None ):
    """Start NAT/forwarding between Mininet and external network
    root: node to access iptables from
    inetIntf: interface for internet access
    subnet: Mininet subnet (default 10.0/8)"""

    # Identify the interface connecting to the mininet network
    if localIntf == None:
        localIntf =  root.defaultIntf()
 
    # Flush any currently active rules
    root.cmd( 'iptables -F' )
    root.cmd( 'iptables -t nat -F' )

    # Create default entries for unmatched traffic
    root.cmd( 'iptables -P INPUT ACCEPT' )
    root.cmd( 'iptables -P OUTPUT ACCEPT' )
    root.cmd( 'iptables -P FORWARD DROP' )

    # Configure NAT
    root.cmd( 'iptables -I FORWARD -i', localIntf, '-d', subnet, '-j DROP' )
    root.cmd( 'iptables -A FORWARD -i', localIntf, '-s', subnet, '-j ACCEPT' )
    root.cmd( 'iptables -A FORWARD -i', inetIntf, '-d', subnet, '-j ACCEPT' )
    root.cmd( 'iptables -t nat -A POSTROUTING -o ', inetIntf, '-j MASQUERADE' )

    # Instruct the kernel to perform forwarding
    root.cmd( 'sysctl net.ipv4.ip_forward=1' )

def fixNetworkManager( root, intf ):
    """Prevent network-manager from messing with our interface,
       by specifying manual configuration in /etc/network/interfaces
       root: a node in the root namespace (for running commands)
       intf: interface name"""
    cfile = '/etc/network/interfaces'
    line = '\niface %s inet manual\n' % intf
    config = open( cfile ).read()
    if ( line ) not in config:
        print('*** Adding', line.strip(), 'to', cfile)
        with open( cfile, 'a' ) as f:
            f.write( line )
    # Probably need to restart network-manager to be safe -
    # hopefully this won't disconnect you
    root.cmd( 'service network-manager restart' )

if __name__ == '__main__':
    setLogLevel( 'info' )
    topology()
   
