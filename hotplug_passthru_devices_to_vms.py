import argparse
import ssl
import sys
import logging

sys.path.append("/usr/lib/vmware/site-packages")

from pyVim.connect import SmartConnect, Disconnect
from pyVim.task import WaitForTask
from pyVmomi import vim

VMDEV_ADD = vim.vm.device.VirtualDeviceSpec.Operation.add

logger = logging.getLogger(__file__)
logging.basicConfig(level=logging.DEBUG)

def getVmObj(si, vmName):
   content = si.RetrieveContent()
   container = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
   for vm in container.view:
      if vm.name == vmName:
         logger.error("Got VM object for %s" % vmName)
         return vm
   logger.error("Failed to get VM with name %s" % vmName)
   return None

def setFixedPassthruHotPlugEnabled(vmObj):
   cspec = vim.vm.ConfigSpec()
   logger.info ('Current Value: %s' % cspec.fixedPassthruHotPlugEnabled)
   cspec.fixedPassthruHotPlugEnabled = True
   task = vmObj.ReconfigVM_Task(cspec)
   WaitForTask(task)
   logger.info('New Value: %s' % cspec.fixedPassthruHotPlugEnabled)

def setMotherboardLayoutAcpi(vmObj):
   cspec = vim.vm.ConfigSpec()
   logger.info ('Current Value: %s' % cspec.motherboardLayout)
   cspec.motherboardLayout = vim.vm.VirtualHardware.MotherboardLayout.acpiHostBridges
   task = vmObj.ReconfigVM_Task(cspec)
   WaitForTask(task)
   logger.info('New Value: %s' % cspec.motherboardLayout)


def getAvailablePcipassthruDevice(vmObj, pciDevAddr):

   availablePciDevices = vmObj.environmentBrowser.QueryConfigTarget().pciPassthrough

   matchedPciDevice = None
   for dev in availablePciDevices:
      if dev.pciDevice.id.lower() == pciDevAddr.lower():
         matchedPciDevice = dev
         break
   return matchedPciDevice

def hotadd(vmObj, pciDevAddr):

   cspec = vim.vm.ConfigSpec()

   virtualDevSpec = vim.vm.device.VirtualDeviceSpec()
   virtualDevSpec.operation = VMDEV_ADD

   pciPassthruDev = vim.vm.device.VirtualPCIPassthrough()
   pciPassthruDev.backing = (vim.vm.device.VirtualPCIPassthrough.DeviceBackingInfo())
   pciPassthruDev.backing.id = pciDevAddr

   targetDev = getAvailablePcipassthruDevice(vmObj, pciDevAddr)
   if not targetDev:
      logger.error("Can not get device with PCI address %s!" % pciDevAddr)
      sys.exit(1)

   pciPassthruDev.backing.systemId = targetDev.systemId
   pciPassthruDev.backing.deviceId = "0x{:x}".format(targetDev.pciDevice.deviceId)
   pciPassthruDev.backing.vendorId = targetDev.pciDevice.vendorId
   pciPassthruDev.backing.deviceName = targetDev.pciDevice.deviceName

   virtualDevSpec.device = pciPassthruDev
   cspec.deviceChange.append(virtualDevSpec)

   logger.info("Start to add device %s" % pciDevAddr)
   task = vmObj.ReconfigVM_Task(cspec)
   WaitForTask(task)
   logger.info("Done!")

def hotremove(vmObj, pciDevAddr):
   pciPassthruDevices = []
   vmDevices = vmObj.config.hardware.device
   for device in vmDevices:
      if isinstance(device, vim.vm.device.VirtualPCIPassthrough):
         pciPassthruDevices.append(device)
   addrDeviceMapping = {device.backing.id: device for device in pciPassthruDevices}
   vmPciPassthruDev = addrDeviceMapping[pciDevAddr]
   logger.info("Got passthru device %s on VM %s" % (pciDevAddr, vmObj.name))

   cspec = vim.vm.ConfigSpec()
   virtualDevSpec = vim.vm.device.VirtualDeviceSpec()
   virtualDevSpec.device = vmPciPassthruDev
   virtualDevSpec.operation = VMDEV_REMOVE

   cspec.deviceChange.append(virtualDevSpec)

   logger.info("Start to remove device %s" % pciDevAddr)
   task = vmObj.ReconfigVM_Task(cspec)
   WaitForTask(task)
   logger.info("Done!")

if __name__ == '__main__':
   parser = argparse.ArgumentParser()
   parser.add_argument('-i', '--vcip',
                        dest='vcip',
                        required=True,
                        help='VC IP to connect to')

   parser.add_argument('-u', '--user',
                       dest='usr',
                       required=True,
                       help='User name to use when connecting to VC')

   parser.add_argument('-p', '--password',
                       dest='pwd',
                       required=True,
                       help='Password to use when connecting to VC')

   parser.add_argument('-v', '--vm',
                       dest='vm',
                       required=True,
                       help='VM name')

   parser.add_argument('-d', '--device',
                          dest='pciDevAddr',
                          help='The address of PCI device with passthrough enabled e.g. 0000:44:00.0')
   parser.add_argument('-o', '--operation',
                       dest = 'op',
                       choices={"add", "remove"},
                       help="Operation to be perfomred \"add\" for hotadd or \"remove\" for hotremove")
   parser.add_argument('-c', '--configure',
                       dest = 'configure',
                       action="store_true",
                       help="Configure given VM to enable future hotadd, VM should be powererd off")

   args = parser.parse_args()
   vcIp = args.vcip
   vcUsr = args.usr
   vcPwd = args.pwd
   vmName = args.vm
   pciDevAddr = args.pciDevAddr

   logger.info("Connecting to VC %s" % vcIp)
   context = ssl._create_unverified_context()
   si = SmartConnect(host=vcIp, user=vcUsr, pwd=vcPwd, sslContext=context)
   logger.info("Created VC session for VC %s" % vcIp)

   vmObj = getVmObj(si, vmName)
   if args.configure:
       logger.info(f"Configuring vm: {vmName} for hotadd")
       setMotherboardLayoutAcpi(vmObj)
       setFixedPassthruHotPlugEnabled(vmObj)

   if args.op == "add":
       hotadd(vmObj, pciDevAddr)
   elif args.op == "remove":
       hotremove(vmObj, pciDevAddr)
   else:
       logger.info("Hotadd/Hotremove not requested, exiting")
