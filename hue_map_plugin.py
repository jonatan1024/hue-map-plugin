#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''

  This Source Code Form is subject to the terms of the Mozilla Public
  License, v. 2.0. If a copy of the MPL was not distributed with this
  file, You can obtain one at http://mozilla.org/MPL/2.0/.

If it is not possible or desirable to put the notice in a particular
file, then You may include the notice in a location (such as a LICENSE
file in a relevant directory) where a recipient would be likely to look
for such a notice.

You may add additional accurate notices of copyright ownership.

'''

import gimp, gimpplugin, math, array
from gimpenums import *
pdb = gimp.pdb
import gtk, gimpui, gimpcolor
from gimpshelf import shelf

class hue_map_plugin(gimpplugin.plugin):
    shelfkey = "hue_map_plugin"
    default_gradient = "Hue gradient"
    layer = None
    
    def start(self):
        gimp.main(self.init, self.quit, self.query, self._run)

    def init(self):
        pass

    def quit(self):
        pass

    def query(self):
        gimp.install_procedure(
            "hue_map_plugin_main",
            "Maps HSV hue spectrum onto a gradient.",
            "Maps HSV hue spectrum onto a gradient.",
            "Jonatan Matejka",
            "Jonatan Matejka",
            "2016",
            "<Image>/_Xtns/Hue map",
            "RGB*",
            PLUGIN,
            [
                #next three parameters are common for all scripts that are inherited from gimpplugin.plugin
                (PDB_INT32, "run_mode", "Run mode"),
                (PDB_IMAGE, "image", "Input image"),
                (PDB_DRAWABLE, "drawable", "Input drawable"),
                #plugin specific parameters
                (PDB_STRING, "gradient_name", "Gradient name"),
                (PDB_INT32, "flatten", "Flatten final image"),
            ],
            []
        )

    def hue_map_plugin_main(self, run_mode, image, drawable, gradient_name = None, flatten = 1):
        #set default gradient name
        if gradient_name is None:
            gradient_name = self.default_gradient
        self.image = image
        self.drawable = drawable
        #create settings storage
        if not shelf.has_key(self.shelfkey):
            self.shelf_store(gradient_name, flatten)
        #initialize dialog
        self.create_dialog()
        #create default hue gradient
        if not self.gradient_exists(self.default_gradient):
            self.reset_gradient()
        
        pdb.gimp_image_undo_group_start(self.image)
        if run_mode == RUN_INTERACTIVE:
            #show and run the dialog
            self.dialog.run()
            #this code runs after the dialog is closed -> cleanup time!
            #destroy preview
            self.layer_destroy()
        else:
            #non-interactive or use last values
            self.ok_clicked(None)
        pdb.gimp_image_undo_group_end(self.image)
        #refresh
        gimp.displays_flush()

    def shelf_store(self, gradient_name, flatten):
        #store the settings
        shelf[self.shelfkey] = {
            "gradient_name":    gradient_name,
            "flatten":          flatten
        }
        
    def gradient_exists(self, gradient_name):
        #filter the gradient list by the name
        gradient_list = gimp.gradients_get_list(gradient_name)
        return len(gradient_list) > 0

    def reset_gradient(self):
        gradient = self.default_gradient
        #delete existing gradient
        if self.gradient_exists(gradient):
            pdb.gimp_gradient_delete(gradient)
        pdb.gimp_gradient_new(gradient)
        #split into 6 segments
        pdb.gimp_gradient_segment_range_split_uniform(gradient, 0, 1, 6)
        #hues as rgbs
        hue = [
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 1.0, 1.0),
            (0.0, 0.0, 1.0),
            (1.0, 0.0, 1.0),
        ]
        #assing hues to segments
        for left in range(0, 6):
            right = (left + 5) % 6
            pdb.gimp_gradient_segment_set_left_color(gradient, left, hue[left], 100.0)
            pdb.gimp_gradient_segment_set_right_color(gradient, right, hue[left], 100.0)
        #update dialog
        self.gradient_button.set_gradient(gradient)
        
    def remap_hue(self):
        #input can be RGB or RGBA
        bpp = self.drawable.bpp
        (bx1, by1, bx2, by2) = self.drawable.mask_bounds
        bw = bx2 - bx1
        bh = by2 - by1
        #input layer offset
        (ox, oy) = self.drawable.offsets
        src_rgn = self.drawable.get_pixel_rgn(bx1, by1, bw, bh, False, False)
        #all the input pixels in one huge array
        #src_rgn[...] returns a packed byte array as a string
        #we unpack this string using python array 
        src_pixels = array.array("B", src_rgn[bx1:bx2, by1:by2])
        
        #delete existing preview layer
        self.layer_destroy()
        #create new output layer
        self.layer = gimp.Layer(self.image, "Hue map", bw, bh, RGBA_IMAGE, 100, NORMAL_MODE)
        #set correct position
        self.layer.set_offsets(bx1 + ox, by1 + oy)
        dest_rgn = self.layer.get_pixel_rgn(0, 0, bw, bh, True, True)
        #all the output pixels
        dest_pixels = array.array("B", dest_rgn[0:bw, 0:bh])
        #output is always RGBA
        dest_bpp = 4
        #add layer into image
        self.image.add_layer(self.layer, 0)
        
        #for 8bit RGB, the hue resolution is 6*256 = 1536
        #sampling in lower resolution (like 360°) would result in color loss
        #we pre-sample the gradient instead of sampling it on each pixel
        #it results in better performance on larger selections (> 39x39 px) 
        num_samples = 6*256
        hue_samples = pdb.gimp_gradient_get_uniform_samples(self.gradient_button.get_gradient(), num_samples+1, False)[1]
        hues = [None] * num_samples
        for i in range(0, num_samples):
            #convert rgb into hue
            sample_rgb = gimpcolor.RGB(hue_samples[i*4+0], hue_samples[i*4+1], hue_samples[i*4+2], hue_samples[i*4+3])
            hues[i] = sample_rgb.to_hsv().h
        #start a progress bar
        gimp.progress_init("Hue map")
        for y in range(0, bh):
            for x in range(0, bw):
                pos = (x + bw*y)*bpp
                #read a pixel as a 3 or 4 byte array
                c_array = src_pixels[pos:(pos+bpp)]
                #create a RGB struct, if there is no alpha, set it to 100% 
                c_rgb = gimpcolor.RGB(c_array[0], c_array[1], c_array[2], c_array[3] if bpp == 4 else 255)
                #RGB -> HSV
                c_hsv = c_rgb.to_hsv()
                #calculate index into hue replacement array
                hue_index = int(round(c_hsv.h * num_samples))
                #replace hue
                c_hsv.h = hues[hue_index]
                #HSV -> RGB
                c_rgb = c_hsv.to_rgb()
                #RGB -> byte array
                c_array[0:dest_bpp] = array.array("B", c_rgb[0:dest_bpp])
                dest_pos = (x + bw*y)*dest_bpp
                #write a pixel into the output array
                dest_pixels[dest_pos:(dest_pos+dest_bpp)] = c_array
            #update the progress bar
            gimp.progress_update(float(y+1)/bh)
        
        #write the output pixel array into the output layer
        dest_rgn[0:bw, 0:bh] = dest_pixels.tostring()
        #apply changes
        self.layer.flush()
        #apply selection mask
        self.layer.merge_shadow(True)
        #refresh
        self.layer.update(0, 0, bw, bh)
        #refresh
        gimp.displays_flush()
        
    def layer_destroy(self):
        if self.layer is not None:
            self.image.remove_layer(self.layer)
            gimp.delete(self.layer)
            self.layer = None 

    def create_dialog(self):
        self.dialog = gimpui.Dialog("Hue map", "hue_map_dialog")
        
        #3x2 non-homogenous table
        self.table = gtk.Table(3, 2, False)
        self.table.set_row_spacings(8)
        self.table.set_col_spacings(8)
        self.table.show()
        
        #gradient selection button
        self.gradient_button = gimpui.GradientSelectButton("Pick a gradient")
        if self.gradient_exists(shelf[self.shelfkey]["gradient_name"]):
            self.gradient_button.set_gradient(shelf[self.shelfkey]["gradient_name"])
        self.gradient_button.show()
        self.table.attach(self.gradient_button, 0, 1, 0, 1)
        
        #reset button
        self.reset_button = gtk.Button("_Reset gradient")
        self.reset_button.show()
        self.reset_button.connect("clicked", self.reset_clicked)
        self.table.attach(self.reset_button, 1, 2, 0, 1)
        
        #flatten checkbox
        self.flatten_check = gtk.CheckButton("Flatten the final image")
        self.flatten_check.set_active(shelf[self.shelfkey]["flatten"])
        self.flatten_check.show()
        self.table.attach(self.flatten_check, 0, 2, 1, 2)
        
        #dialog inner frames
        #there is a table inside a hbox inside a vbox
        self.dialog.vbox.hbox1 = gtk.HBox(False, 7)
        self.dialog.vbox.hbox1.show()
        self.dialog.vbox.pack_start(self.dialog.vbox.hbox1, True, True, 7)
        self.dialog.vbox.hbox1.pack_start(self.table, True, True, 7)
        
        #buttons at the bottom
        #Preview, Ok and Cancel
        self.preview_button = gtk.Button("_Preview")
        self.preview_button.show()
        self.preview_button.connect("clicked", self.preview_clicked)
        if gtk.alternative_dialog_button_order():
            self.dialog.action_area.add(self.preview_button)
            self.ok_button = self.dialog.add_button(gtk.STOCK_OK, gtk.RESPONSE_OK)
            self.cancel_button = self.dialog.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL)
        else:
            self.cancel_button = self.dialog.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL)
            self.ok_button = self.dialog.add_button(gtk.STOCK_OK, gtk.RESPONSE_OK)
            self.dialog.action_area.add(self.preview_button)
        self.ok_button.connect("clicked", self.ok_clicked)
        self.cancel_button.connect("clicked", self.cancel_clicked)
        
    def preview_clicked(self, widget):
        self.remap_hue()

    def reset_clicked(self, widget):
        self.reset_gradient()
        
    def ok_clicked(self, widget):
        self.remap_hue()
        if self.flatten_check.get_active():
            pdb.gimp_image_flatten(self.image)
        #we want to keep the preview layer so we forget that we made it
        self.layer = None
        #save the settings
        self.shelf_store(self.gradient_button.get_gradient(), self.flatten_check.get_active())
        
    def cancel_clicked(self, widget):
        #all the cleanup is done in the main function
        pass

if __name__ == '__main__':
    hue_map_plugin().start()
